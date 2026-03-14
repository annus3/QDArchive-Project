"""
Pipeline orchestrator — coordinates harvesters and downloads.
"""

import logging
import os

from . import config
from .database import Database
from .harvesters.dataverse import DataverseHarvester
from .harvesters.columbia import ColumbiaHarvester

logger = logging.getLogger(__name__)


def _create_harvester(repo_key: str, db: Database):
    """Factory: create the right harvester for a repository key."""
    repo_type = config.REPOSITORIES[repo_key]["type"]
    if repo_type == "dataverse":
        return DataverseHarvester(db, repo_key)
    elif repo_type == "columbia":
        return ColumbiaHarvester(db, repo_key)
    else:
        raise ValueError(f"Unknown repo type: {repo_type}")


def run_harvest(repos: list[str] | None = None, queries: list[str] | None = None,
                db: Database | None = None):
    """
    Phase 1: Search repositories and collect metadata + file info.
    """
    db = db or Database()
    repos = repos or [k for k, v in config.REPOSITORIES.items() if v.get("enabled")]

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
            harvester = _create_harvester(repo_key, db)
            harvester.harvest(queries)
        except Exception as exc:
            logger.error("Harvester %s failed: %s", repo_key, exc, exc_info=True)
            db.log_challenge("api_error", f"Harvester {repo_key} crashed: {exc}",
                             source_repository=repo_key)

    return db


def run_downloads(repos: list[str] | None = None, only_qda: bool = False,
                  db: Database | None = None):
    """
    Phase 2: Download files for harvested projects.
    """
    db = db or Database()
    repos = repos or [k for k, v in config.REPOSITORIES.items() if v.get("enabled")]

    for repo_key in repos:
        if repo_key not in config.REPOSITORIES:
            continue
        if not config.REPOSITORIES[repo_key].get("enabled"):
            continue

        logger.info("=" * 60)
        logger.info("DOWNLOADING: %s", config.REPOSITORIES[repo_key]["name"])
        logger.info("=" * 60)

        # Get projects pending download
        query = "SELECT id FROM projects WHERE source_repository=? AND download_status='pending'"
        if only_qda:
            query += " AND has_qda_files=1"
        rows = db.conn.execute(query, (repo_key,)).fetchall()

        logger.info("  %d projects to download", len(rows))

        harvester = _create_harvester(repo_key, db)
        for row in rows:
            try:
                harvester.download_project_files(row["id"])
            except Exception as exc:
                logger.error("Download failed for project %d: %s", row["id"], exc)
                db.log_challenge("api_error", f"Download crash for project {row['id']}: {exc}",
                                 project_id=row["id"], source_repository=repo_key)

    return db


def run_full_pipeline(repos: list[str] | None = None, queries: list[str] | None = None,
                      download: bool = True, only_qda: bool = False):
    """
    Run the full pipeline: harvest → download → export.
    """
    os.makedirs(config.DATA_DIR, exist_ok=True)
    os.makedirs(config.EXPORTS_DIR, exist_ok=True)

    db = Database()

    # Phase 1: Harvest metadata
    logger.info("╔══════════════════════════════════════════════════════════╗")
    logger.info("║            PHASE 1: HARVESTING METADATA                ║")
    logger.info("╚══════════════════════════════════════════════════════════╝")
    run_harvest(repos, queries, db)

    # Phase 2: Download files
    if download:
        logger.info("╔══════════════════════════════════════════════════════════╗")
        logger.info("║            PHASE 2: DOWNLOADING FILES                   ║")
        logger.info("╚══════════════════════════════════════════════════════════╝")
        run_downloads(repos, only_qda, db)

    # Phase 3: Export
    logger.info("╔══════════════════════════════════════════════════════════╗")
    logger.info("║            PHASE 3: EXPORTING CSV                       ║")
    logger.info("╚══════════════════════════════════════════════════════════╝")
    # Export per-repo + combined CSVs
    for repo_key in (repos or [k for k, v in config.REPOSITORIES.items() if v.get("enabled")]):
        repo_dir = os.path.join(config.EXPORTS_DIR, repo_key)
        os.makedirs(repo_dir, exist_ok=True)
        db.export_projects_csv(os.path.join(repo_dir, "projects.csv"), source_repository=repo_key)
        db.export_files_csv(os.path.join(repo_dir, "files.csv"), source_repository=repo_key)
        db.export_challenges_csv(os.path.join(repo_dir, "technical_challenges.csv"), source_repository=repo_key)
    combined_dir = os.path.join(config.EXPORTS_DIR, "combined")
    os.makedirs(combined_dir, exist_ok=True)
    db.export_projects_csv(os.path.join(combined_dir, "projects.csv"))
    db.export_files_csv(os.path.join(combined_dir, "files.csv"))
    db.export_challenges_csv(os.path.join(combined_dir, "technical_challenges.csv"))

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
