#!/usr/bin/env python3
"""
build_isic_taxonomy.py — Build the ISIC Rev. 5 division taxonomy artifact.

One-off, offline builder. Reads the official ISIC Rev. 5 explanatory-notes
workbook and emits a division-level corpus used by the Phase 2 classifier.

Usage:
    python build_isic_taxonomy.py
    python build_isic_taxonomy.py 
                                    --dst pipeline/data/isic_taxonomy.json
"""

import argparse
import html
import json
import os
import re
import sys
import zipfile

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
DEFAULT_SRC = os.path.join(PROJECT_ROOT, "docs", "ISIC5_Exp_Notes_11Mar2024.xlsx")
DEFAULT_DST = os.path.join(PROJECT_ROOT, "pipeline", "data", "isic_taxonomy.json")

DIVISION_CODE_RE = re.compile(r"^[A-U][0-9]{2}$")
# Bullet / list markers and control chars to blank out (per §16 normalization).
_MARKERS_RE = re.compile(r"[\u25e6\u2022\u25aa\u2023\-\u2013\u2014\r\n\t/\\_.:;()\[\]]+")
_WS_RE = re.compile(r"\s+")


def _clean(text: str) -> str:
    """Lower-case, blank out markers/punctuation, collapse whitespace."""
    if not text:
        return ""
    text = _MARKERS_RE.sub(" ", text)
    text = _WS_RE.sub(" ", text)
    return text.strip().lower()


def _read_shared_strings(zf: zipfile.ZipFile) -> list[str]:
    try:
        raw = zf.read("xl/sharedStrings.xml").decode("utf-8", "ignore")
    except KeyError:
        return []
    out = []
    for si in re.findall(r"<si>(.*?)</si>", raw, re.S):
        out.append(html.unescape("".join(re.findall(r"<t[^>]*>(.*?)</t>", si, re.S))))
    return out


def _sheet_path_map(zf: zipfile.ZipFile) -> dict[str, str]:
    wb = zf.read("xl/workbook.xml").decode("utf-8", "ignore")
    rels = zf.read("xl/_rels/workbook.xml.rels").decode("utf-8", "ignore")
    sheets = re.findall(r'<sheet [^>]*name="([^"]+)"[^>]*r:id="([^"]+)"', wb)
    relmap = dict(re.findall(r'Id="([^"]+)"[^>]*Target="([^"]+)"', rels))
    return {name: "xl/" + relmap[rid].lstrip("/") for name, rid in sheets}


def _parse_sheet(zf: zipfile.ZipFile, path: str, shared: list[str]) -> list[dict[str, str]]:
    xml = zf.read(path).decode("utf-8", "ignore")
    rows: list[dict[str, str]] = []
    for rm in re.finditer(r"<row[^>]*>(.*?)</row>", xml, re.S):
        cells: dict[str, str] = {}
        body = rm.group(1)
        for cm in re.finditer(
            r'<c r="([A-Z]+)\d+"(?:[^>]*t="([^"]+)")?[^>]*>'
            r"(?:<v>(.*?)</v>|<is>(.*?)</is>)?</c>",
            body,
            re.S,
        ):
            col, typ, v, iss = cm.group(1), cm.group(2), cm.group(3), cm.group(4)
            if v is not None and typ == "s":
                val = shared[int(v)]
            elif v is not None:
                val = html.unescape(v)
            elif iss is not None:
                val = html.unescape("".join(re.findall(r"<t[^>]*>(.*?)</t>", iss, re.S)))
            else:
                val = ""
            cells[col] = val
        rows.append(cells)
    return rows


def build_taxonomy(src_path: str) -> dict[str, dict[str, str]]:
    if not os.path.exists(src_path):
        raise FileNotFoundError(f"ISIC workbook not found: {src_path}")

    with zipfile.ZipFile(src_path) as zf:
        shared = _read_shared_strings(zf)
        sheet_paths = _sheet_path_map(zf)
        if "ISIC5" not in sheet_paths:
            raise ValueError("Workbook has no 'ISIC5' sheet")
        isic_rows = _parse_sheet(zf, sheet_paths["ISIC5"], shared)
        division_rows = (
            _parse_sheet(zf, sheet_paths["Divisions"], shared)
            if "Divisions" in sheet_paths
            else []
        )

    # Division codes from the flat 'Divisions' index sheet (for validation).
    division_codes = {
        r.get("A", "").strip()
        for r in division_rows
        if DIVISION_CODE_RE.match(r.get("A", "").strip())
    }

    taxonomy: dict[str, dict[str, str]] = {}
    for r in isic_rows:
        code = (r.get("A", "") or "").strip()
        if len(code) != 3 or not DIVISION_CODE_RE.match(code):
            continue  # keep divisions only (section=1 char, group=4, class=5)
        title = (r.get("C", "") or "").strip()
        introductory = r.get("D", "") or ""
        includes = r.get("E", "") or ""
        includes_also = r.get("F", "") or ""
        # Title weighted ×3 (§16); Excludes (col G) deliberately omitted.
        corpus = " ".join([title, title, title, introductory, includes, includes_also])
        taxonomy[code] = {"title": title, "text": _clean(corpus)}

    _validate(taxonomy, division_codes)
    return taxonomy


def _validate(taxonomy: dict[str, dict[str, str]], division_codes: set[str]) -> None:
    if len(taxonomy) != 86:
        raise ValueError(f"Expected 86 divisions, got {len(taxonomy)}")
    for code, entry in taxonomy.items():
        if not DIVISION_CODE_RE.match(code):
            raise ValueError(f"Bad division code: {code!r}")
        if not entry["text"].strip():
            raise ValueError(f"Empty corpus text for division {code}")
        if not entry["title"].strip():
            raise ValueError(f"Empty title for division {code}")
    if division_codes and set(taxonomy.keys()) != division_codes:
        missing = division_codes - set(taxonomy.keys())
        extra = set(taxonomy.keys()) - division_codes
        raise ValueError(
            f"Key set != Divisions sheet. missing={sorted(missing)} extra={sorted(extra)}"
        )


def main() -> int:
    ap = argparse.ArgumentParser(description="Build the ISIC Rev. 5 division taxonomy JSON.")
    ap.add_argument("--src", default=DEFAULT_SRC, help="ISIC5 workbook (default: %(default)s)")
    ap.add_argument("--dst", default=DEFAULT_DST, help="Output JSON (default: %(default)s)")
    args = ap.parse_args()

    taxonomy = build_taxonomy(args.src)
    os.makedirs(os.path.dirname(args.dst), exist_ok=True)
    with open(args.dst, "w", encoding="utf-8") as fh:
        json.dump(taxonomy, fh, ensure_ascii=False, indent=1, sort_keys=True)

    print(f"Built ISIC taxonomy → {args.dst}")
    print(f"  divisions : {len(taxonomy)}")
    sample = next(iter(taxonomy.items()))
    print(f"  sample    : {sample[0]} — {sample[1]['title']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
