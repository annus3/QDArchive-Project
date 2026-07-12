"""
pipeline/classifier.py — Phase 2 classification engine.

Two responsibilities, both pure and unit-testable:

1. ``derive_project_type`` — reduce a project's file categories to a PROJECT_TYPE
   (``QDA_PROJECT`` / ``QD_PROJECT`` / ``OTHER_PROJECT`` / ``NOT_A_PROJECT``),
   exactly as specified in docs/CLASSIFICATION_RESEARCH.md §1/§10.1.  It reuses the
   existing ``file_category`` produced by ``harvesters.base.classify_file`` — no new
   extension lists are introduced here.

2. ``IsicClassifier`` — rank a piece of text against the 86 ISIC Rev. 5 divisions
   using a dependency-light TF-IDF + cosine model built over the taxonomy artifact
   (``pipeline/data/isic_taxonomy.json``).  It returns a primary division, an optional
   secondary division (only above a similarity ratio gate), a confidence score, and
   searchable tags.  There is **no default bucket** — unmatched text yields ``None``.

The engine uses only the standard library.
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from dataclasses import dataclass, field

from . import config


# ── Tokenisation ────────────────────────────────────────────────────────────
# Alphabetic tokens of length >= 2 (drops digits, cross-reference numbers, and
# single letters).  Lower-cased by the caller-facing helpers.
_TOKEN_RE = re.compile(r"[a-z]{2,}")

# Compact English stop-word list plus a few structural boilerplate words that
# appear in the ISIC explanatory notes ("this division includes ...").
STOPWORDS = frozenset(
    """
    a an and are as at be by for from has have in into is it its of on or that the
    their this to was were will with which include includes including included also
    such other others via per etc eg ie see note than then them they these those but
    not no any all can may only more most some same not-elsewhere nec elsewhere
    division divisions group groups class classes section sections activity activities
    about above after again against below before being between both during each few
    further here itself over own through under until very what when where while who
    whom why would could should out off down up if because so too just non use used
    """.split()
)


def tokenize(text: str) -> list[str]:
    """Lower-case, extract alphabetic tokens, drop stop-words."""
    if not text:
        return []
    return [t for t in _TOKEN_RE.findall(text.lower()) if t not in STOPWORDS]


def load_name_map(taxonomy_path: str | None = None) -> dict[str, str]:
    """Load ``{division_code: title}`` from the taxonomy artifact (no model fit)."""
    path = taxonomy_path or config.ISIC_TAXONOMY_PATH
    with open(path, "r", encoding="utf-8") as fh:
        taxonomy: dict[str, dict[str, str]] = json.load(fh)
    return {code: entry.get("title", "") for code, entry in taxonomy.items()}


def display_class(code: str | None, name_map: dict[str, str]) -> str:
    """Render a division code as ``CODE — Division Name`` (empty if code is None)."""
    if not code:
        return ""
    title = name_map.get(code, "")
    return f"{code} — {title}" if title else code


# ── Project-type derivation (spec Step 1) ───────────────────────────────────
def derive_project_type(has_analysis: bool, has_primary: bool, has_any_file: bool) -> str:
    """Derive PROJECT_TYPE from file categories, in strict priority order."""
    if has_analysis:
        return config.PROJECT_TYPE_QDA
    if has_primary:
        return config.PROJECT_TYPE_QD
    if has_any_file:
        return config.PROJECT_TYPE_OTHER
    return config.PROJECT_TYPE_NONE


# ── Input text composition ──────────────────────────────────────────────────
def project_text(
    *,
    title: str = "",
    description: str = "",
    scope: str = "",
    keywords: list[str] | None = None,
    licenses: list[str] | None = None,
    authors: list[str] | None = None,
    file_names: list[str] | None = None,
) -> str:
    """Compose the project-level classification text ("sum of its files" + metadata)."""
    parts: list[str] = [title or "", description or "", scope or ""]
    parts.extend(keywords or [])
    parts.extend(licenses or [])
    parts.extend(authors or [])
    parts.extend(file_names or [])
    return " ".join(p for p in parts if p)


def file_text(file_name: str = "") -> str:
    """Compose the per-file classification text (file name only, deferred content)."""
    return file_name or ""


# ── Classification result ───────────────────────────────────────────────────
@dataclass
class ClassificationResult:
    primary: str | None = None            # ISIC division code, e.g. "R86"
    secondary: str | None = None          # runner-up division code or None
    confidence: float = 0.0               # cosine similarity of the primary (0..1)
    tags: list[str] = field(default_factory=list)

    @property
    def is_classified(self) -> bool:
        return self.primary is not None


# ── TF-IDF + cosine ISIC classifier ─────────────────────────────────────────
class IsicClassifier:
    """Rank text against ISIC Rev. 5 divisions via TF-IDF + cosine similarity."""

    def __init__(
        self,
        taxonomy_path: str | None = None,
        secondary_min_ratio: float | None = None,
        tag_count: int | None = None,
        min_primary_confidence: float | None = None,
    ):
        self.secondary_min_ratio = (
            config.SECONDARY_MIN_RATIO if secondary_min_ratio is None else secondary_min_ratio
        )
        self.tag_count = config.CLASSIFICATION_TAG_COUNT if tag_count is None else tag_count
        self.min_primary_confidence = (
            config.MIN_PRIMARY_CONFIDENCE
            if min_primary_confidence is None
            else min_primary_confidence
        )

        path = taxonomy_path or config.ISIC_TAXONOMY_PATH
        with open(path, "r", encoding="utf-8") as fh:
            taxonomy: dict[str, dict[str, str]] = json.load(fh)
        if not taxonomy:
            raise ValueError(f"Empty ISIC taxonomy: {path}")

        self._fit(taxonomy)

    # -- fitting -------------------------------------------------------------
    def _fit(self, taxonomy: dict[str, dict[str, str]]) -> None:
        codes = list(taxonomy.keys())
        doc_tokens: dict[str, list[str]] = {
            c: tokenize(taxonomy[c].get("text", "")) for c in codes
        }
        n_docs = len(codes)

        df: Counter[str] = Counter()
        for toks in doc_tokens.values():
            df.update(set(toks))

        # Smoothed IDF (sklearn-style): ln((1+N)/(1+df)) + 1.
        self._idf: dict[str, float] = {
            term: math.log((1 + n_docs) / (1 + freq)) + 1.0 for term, freq in df.items()
        }

        # Pre-computed, L2-normalised TF-IDF vector per division.
        self._division_vectors: dict[str, dict[str, float]] = {}
        for code, toks in doc_tokens.items():
            self._division_vectors[code] = self._vectorize(Counter(toks))

    def _vectorize(self, tf: Counter[str]) -> dict[str, float]:
        """Build an L2-normalised TF-IDF vector restricted to the fitted vocabulary."""
        vec = {t: c * self._idf[t] for t, c in tf.items() if t in self._idf}
        norm = math.sqrt(sum(w * w for w in vec.values()))
        if norm == 0.0:
            return {}
        return {t: w / norm for t, w in vec.items()}

    # -- classification ------------------------------------------------------
    def classify(self, text: str) -> ClassificationResult:
        toks = tokenize(text)
        if not toks:
            return ClassificationResult()

        tf = Counter(toks)
        # Raw (un-normalised) weights are used for tag extraction.
        raw = {t: c * self._idf[t] for t, c in tf.items() if t in self._idf}
        if not raw:
            return ClassificationResult()
        qnorm = math.sqrt(sum(w * w for w in raw.values()))
        if qnorm == 0.0:
            return ClassificationResult()
        query = {t: w / qnorm for t, w in raw.items()}

        scored: list[tuple[str, float]] = []
        for code, dvec in self._division_vectors.items():
            # cosine = dot product of two L2-normalised sparse vectors.
            if len(query) <= len(dvec):
                sim = sum(w * dvec.get(t, 0.0) for t, w in query.items())
            else:
                sim = sum(w * query.get(t, 0.0) for t, w in dvec.items())
            if sim > 0.0:
                scored.append((code, sim))

        if not scored:
            return ClassificationResult()

        scored.sort(key=lambda kv: kv[1], reverse=True)
        primary_code, primary_score = scored[0]

        # Low-confidence → NULL (no default bucket): a weak best match is not a
        # real classification (CLASSIFICATION_RESEARCH.md §10.2).
        if primary_score < self.min_primary_confidence:
            return ClassificationResult()

        secondary_code = None
        if len(scored) > 1:
            second_code, second_score = scored[1]
            if second_score >= self.secondary_min_ratio * primary_score:
                secondary_code = second_code

        tags = [t for t, _ in sorted(raw.items(), key=lambda kv: kv[1], reverse=True)][
            : self.tag_count
        ]

        return ClassificationResult(
            primary=primary_code,
            secondary=secondary_code,
            confidence=round(primary_score, 4),
            tags=tags,
        )
