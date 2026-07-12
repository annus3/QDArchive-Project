"""
Pipeline orchestrator — coordinates harvesters and downloads.
"""

import logging
import os

from . import config
from .database import Database
from .harvesters.dataverse import DataverseHarvester
from .harvesters.columbia import ColumbiaHarvester
from .progress import ProgressTracker

logger = logging.getLogger(__name__)



# Download budget tracker (shared across repos and passes)
class DownloadBudget:
    """Track cumulative download size against a global cap."""

    def __init__(self, max_bytes: int, existing_bytes: int = 0):
        self.max_bytes = max_bytes      # 0 = unlimited
        self.used_bytes = existing_bytes

    def can_afford(self, size_bytes: int) -> bool:
        if self.max_bytes <= 0:
            return True
        return (self.used_bytes + size_bytes) <= self.max_bytes

    def record(self, size_bytes: int):
        self.used_bytes += size_bytes

    @property
    def exhausted(self) -> bool:
        if self.max_bytes <= 0:
            return False
        return self.used_bytes >= self.max_bytes

    @property
    def remaining(self) -> int:
        if self.max_bytes <= 0:
            return float("inf")
        return max(0, self.max_bytes - self.used_bytes)

    def __repr__(self):
        used_mb = self.used_bytes / 1024 / 1024
        max_mb = self.max_bytes / 1024 / 1024 if self.max_bytes else 0
        return f"DownloadBudget({used_mb:.0f}/{max_mb:.0f} MB)"


def _create_harvester(repo_key: str, db: Database, progress=None):
    """Factory: create the right harvester for a repository key."""
    repo_type = config.REPOSITORIES[repo_key]["type"]
    if repo_type == "dataverse":
        return DataverseHarvester(db, repo_key, progress=progress)
    elif repo_type == "columbia":
        return ColumbiaHarvester(db, repo_key, progress=progress)
    else:
        raise ValueError(f"Unknown repo type: {repo_type}")


def run_harvest(repos: list[str] | None = None, queries: list[str] | None = None,
                db: Database | None = None, fresh: bool = False):
    """
    Phase 1: Search repositories and collect metadata + file info.
    """
    db = db or Database()
    repos = repos or [k for k, v in config.REPOSITORIES.items() if v.get("enabled")]

    progress = ProgressTracker()
    if fresh:
        progress.clear()
    elif progress.is_stale():
        logger.warning("Progress file is stale (>72h old) — clearing and starting fresh")
        progress.clear()

    for repo_key in repos:
        if repo_key not in config.REPOSITORIES:
            logger.warning("Unknown repository: %s — skipping", repo_key)
            continue
        if not config.REPOSITORIES[repo_key].get("enabled"):
            logger.info("Repository %s is disabled — skipping", repo_key)
            continue

        logger.info("=" * 60)
        logger.info("HARVESTING: %s", config.REPOSITORIES[repo_key]["name"])
        logger.info("=" * 60)
        try:
            harvester = _create_harvester(repo_key, db, progress=progress)
            harvester.harvest(queries)
            db.flush()
        except Exception as exc:
            logger.error("Harvester %s failed: %s", repo_key, exc, exc_info=True)
            db.log_challenge("api_error", f"Harvester {repo_key} crashed: {exc}",
                             source_repository=repo_key)

    return db


def _get_existing_download_size() -> int:
    """Measure bytes already on disk under data/."""
    total = 0
    if os.path.isdir(config.DATA_DIR):
        for dirpath, _dirnames, filenames in os.walk(config.DATA_DIR):
            for f in filenames:
                total += os.path.getsize(os.path.join(dirpath, f))
    return total


def run_downloads(repos: list[str] | None = None, only_qda: bool = False,
                  db: Database | None = None):
    """
    Phase 2: Download files for harvested projects.

    Uses a two-pass strategy:
      Pass 1 — QDA (analysis) files first, across ALL repos.
      Pass 2 — Remaining (primary + additional) files, across ALL repos.

    Both passes share a global byte budget (``MAX_TOTAL_DOWNLOAD_GB``).
    If ``only_qda`` is True, Pass 2 is skipped entirely.
    Previously failed downloads are retried in both passes.
    """
    db = db or Database()
    repos = repos or [k for k, v in config.REPOSITORIES.items() if v.get("enabled")]

    # Build shared budget from existing disk usage
    existing = _get_existing_download_size()
    max_bytes = int(config.MAX_TOTAL_DOWNLOAD_GB * 1024 * 1024 * 1024) if config.MAX_TOTAL_DOWNLOAD_GB else 0
    budget = DownloadBudget(max_bytes, existing_bytes=existing)
    logger.info("Download budget: %s  (%.1f MB already on disk)",
                budget, existing / 1024 / 1024)

    # ── Pass 1: QDA (analysis) files ─────────────────────────────────
    logger.info("─" * 60)
    logger.info("  PASS 1/2 : QDA (analysis) files")
    logger.info("─" * 60)
    for repo_key in repos:
        if budget.exhausted:
            logger.info("Budget exhausted — stopping QDA pass")
            break
        _download_pass(repo_key, db, category="analysis", budget=budget)

    # ── Pass 2: non-QDA files (primary + additional) ─────────────────
    if not only_qda:
        logger.info("─" * 60)
        logger.info("  PASS 2/2 : non-QDA files (primary + additional)")
        logger.info("─" * 60)
        for repo_key in repos:
            if budget.exhausted:
                logger.info("Budget exhausted — stopping non-QDA pass")
                break
            _download_pass(repo_key, db, category=None, budget=budget)

    logger.info("Downloads complete. %s", budget)
    return db


def _download_pass(repo_key: str, db: Database, category: str | None,
                   budget: DownloadBudget):
    """Run a single download pass for one repository.

    Args:
        category: ``"analysis"`` for QDA-only, ``None`` for non-QDA files.
    """
    if repo_key not in config.REPOSITORIES:
        return
    if not config.REPOSITORIES[repo_key].get("enabled"):
        return

    label = category or "non-QDA"
    logger.info("[%s] Downloading %s files …", repo_key, label)

    # Select projects: for QDA pass pick QDA projects; for non-QDA pass pick all
    # Include 'skipped' status because previous runs may have skipped QDA files
    # that were not in the old DOWNLOAD_EXTENSIONS whitelist.
    if category == "analysis":
        query = ("SELECT id FROM projects WHERE source_repository=? "
                 "AND has_qda_files=1 "
                 "AND download_status IN ('pending','failed','skipped')")
    else:
        query = ("SELECT id FROM projects WHERE source_repository=? "
                 "AND download_status IN ('pending','failed')")
    rows = db.conn.execute(query, (repo_key,)).fetchall()
    logger.info("  %d projects to process", len(rows))

    harvester = _create_harvester(repo_key, db)
    for row in rows:
        if budget.exhausted:
            logger.info("  Budget exhausted mid-pass — stopping")
            return
        try:
            harvester.download_project_files(row["id"], category=category, budget=budget)
        except Exception as exc:
            logger.error("Download failed for project %d: %s", row["id"], exc)
            db.log_challenge("api_error",
                             f"Download crash for project {row['id']}: {exc}",
                             project_id=row["id"], source_repository=repo_key)


def run_classification(db: Database | None = None, repos: list[str] | None = None):
    """
    Part 2 (classification phase): classify projects and primary files.

    Step 1 (all projects): derive ``PROJECT_TYPE`` from the file categories already
    stored during acquisition (reuses ``file_category``; no new extension lists).

    Steps 2–3 (QDA_PROJECT + QD_PROJECT only, by repository): assign an ISIC Rev. 5
    division to the project (as the sum of its files + metadata) and to each primary
    data file, using the dependency-light TF-IDF classifier. No default bucket.
    """
    from .classifier import (
        IsicClassifier, derive_project_type, project_text, file_text,
    )

    db = db or Database()
    repos = repos or [k for k, v in config.REPOSITORIES.items() if v.get("enabled")]

    # ── Step 1: derive PROJECT_TYPE for every project ────────────────────────
    logger.info("─" * 60)
    logger.info("  Deriving project types (all projects)")
    logger.info("─" * 60)
    type_counts = {t: 0 for t in config.PROJECT_TYPES}
    for summ in db.get_project_file_summary():
        ptype = derive_project_type(
            bool(summ["has_analysis"]), bool(summ["has_primary"]), summ["n_files"] > 0
        )
        db.set_project_type(summ["project_id"], ptype)
        type_counts[ptype] += 1
    db.flush()
    logger.info("  Project types: %s", type_counts)

    # ── Steps 2–3: ISIC classification of QDA/QD projects + their primary files ─
    clf = IsicClassifier()
    n_projects = 0
    n_files = 0
    for repo_key in repos:
        if repo_key not in config.REPOSITORIES:
            logger.warning("Unknown repository: %s — skipping", repo_key)
            continue
        projects = db.get_classifiable_projects(repo_key, config.CLASSIFIABLE_TYPES)
        logger.info("[%s] ISIC-classifying %d projects …", repo_key, len(projects))

        for proj in projects:
            pid = proj["id"]
            files = db.get_files_for_project_ordered(pid)

            text = project_text(
                title=proj.get("title") or "",
                description=proj.get("description") or "",
                scope=proj.get("project_scope") or "",
                keywords=db.get_keywords_for_project(pid),
                licenses=db.get_licenses_for_project(pid),
                authors=[p["name"] for p in db.get_persons_for_project(pid)],
                file_names=[f.get("file_name") or "" for f in files],
            )
            res = clf.classify(text)
            db.set_project_classification(
                pid, res.primary, res.secondary, res.confidence, res.tags
            )
            n_projects += 1

            # Per-file classification of primary data files (spec Step 3).
            for f in files:
                if (f.get("file_category") or "").lower() != "primary":
                    continue
                fres = clf.classify(file_text(f.get("file_name") or ""))
                db.set_file_classification(
                    f["id"], fres.primary, fres.secondary, fres.confidence
                )
                n_files += 1
        db.flush()

    db.flush()
    logger.info("Classification complete: %d projects, %d primary files", n_projects, n_files)
    return db


def run_full_pipeline(repos: list[str] | None = None, queries: list[str] | None = None,
                      download: bool = True, only_qda: bool = False,
                      fresh: bool = False):
    """
    Run the full pipeline: harvest → download → export.
    """
    os.makedirs(config.DATA_DIR, exist_ok=True)
    os.makedirs(config.EXPORTS_DIR, exist_ok=True)

    db = Database()

    # Phase 1: Harvest metadata
    logger.info("╔══════════════════════════════════════════════════════════╗")
    logger.info("║            PHASE 1: HARVESTING METADATA                  ║")
    logger.info("╚══════════════════════════════════════════════════════════╝")
    run_harvest(repos, queries, db, fresh=fresh)

    # Clear progress after successful harvest
    ProgressTracker().clear()

    # Phase 2: Download files
    if download:
        logger.info("╔══════════════════════════════════════════════════════════╗")
        logger.info("║            PHASE 2: DOWNLOADING FILES                    ║")
        logger.info("╚══════════════════════════════════════════════════════════╝")
        run_downloads(repos, only_qda, db)

    # Phase 3: Export
    logger.info("╔══════════════════════════════════════════════════════════╗")
    logger.info("║            PHASE 3: EXPORTING CSV                        ║")
    logger.info("╚══════════════════════════════════════════════════════════╝")
    # Export per-repo + combined CSVs
    for repo_key in (repos or [k for k, v in config.REPOSITORIES.items() if v.get("enabled")]):
        repo_dir = os.path.join(config.EXPORTS_DIR, repo_key)
        os.makedirs(repo_dir, exist_ok=True)
        db.export_projects_csv(os.path.join(repo_dir, "projects.csv"), source_repository=repo_key)
        db.export_files_csv(os.path.join(repo_dir, "files.csv"), source_repository=repo_key)
        db.export_challenges_csv(os.path.join(repo_dir, "technical_challenges.csv"), source_repository=repo_key)
        db.export_keywords_csv(os.path.join(repo_dir, "keywords.csv"), source_repository=repo_key)
        db.export_person_role_csv(os.path.join(repo_dir, "person_role.csv"), source_repository=repo_key)
        db.export_licenses_csv(os.path.join(repo_dir, "licenses.csv"), source_repository=repo_key)
    combined_dir = os.path.join(config.EXPORTS_DIR, "combined")
    os.makedirs(combined_dir, exist_ok=True)
    db.export_projects_csv(os.path.join(combined_dir, "projects.csv"))
    db.export_files_csv(os.path.join(combined_dir, "files.csv"))
    db.export_challenges_csv(os.path.join(combined_dir, "technical_challenges.csv"))
    db.export_keywords_csv(os.path.join(combined_dir, "keywords.csv"))
    db.export_person_role_csv(os.path.join(combined_dir, "person_role.csv"))
    db.export_licenses_csv(os.path.join(combined_dir, "licenses.csv"))

    # Summary
    summary = db.summary()
    logger.info("=" * 60)
    logger.info("PIPELINE SUMMARY")
    logger.info("=" * 60)
    logger.info("  Total projects discovered : %d", summary["total_projects"])
    logger.info("  Projects with QDA files   : %d", summary["projects_with_qda"])
    logger.info("  Projects downloaded        : %d", summary["downloaded_projects"])
    logger.info("  Total files cataloged      : %d", summary["total_files"])
    logger.info("  Technical challenges       : %d", summary["technical_challenges"])
    logger.info("=" * 60)

    db.close()
    return summary
