#!/usr/bin/env python3
"""
run_pipeline.py — Entry point for the QDArchive pipeline.

Part 1 — Acquisition (harvest + download + CSV export):
    python run_pipeline.py                          # Full pipeline (harvest + download all repos)
    python run_pipeline.py --harvest-only           # Only collect metadata, no downloads
    python run_pipeline.py --repos harvard_dataverse columbia_oral_history
    python run_pipeline.py --qda-only               # Only download projects that have QDA files
    python run_pipeline.py --queries "qdpx" "NVivo" # Custom search queries
    python run_pipeline.py --fresh                  # Ignore saved progress, harvest from scratch

Part 2 — Classification (project types + ISIC Rev. 5 divisions + deliverables):
    python run_pipeline.py --classify-only          # Classify the existing operational DB and
                                                    # emit the deliverables: classification DB,
                                                    # XLSX table, vector PDF report, statistics
    python run_pipeline.py --classify               # Run acquisition first, then classification
    python run_pipeline.py --classify-only --repos harvard_dataverse
                                                    # Classify a single repository

Diagnostics:
    python run_pipeline.py --log-level DEBUG        # Verbose logging for any of the above
"""

import argparse
import logging
import sys
import os

# Ensure project root is on the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from pipeline.orchestrator import run_full_pipeline, run_classification
from pipeline import config


def _run_classification_phase(repos):
    """Phase 2: classify the operational DB, emit deliverables, build the class DB."""
    from pipeline import reports
    from pipeline.database import Database
    import sub_db

    db = Database()
    run_classification(db, repos=repos)

    out_dir = os.path.join(config.EXPORTS_DIR, "classification")
    xlsx_path = os.path.join(out_dir, "23221189-sq26-classification.xlsx")
    pdf_path = os.path.join(out_dir, "23221189-sq26-classification-report.pdf")
    reports.export_xlsx(db, xlsx_path, repos=repos)
    reports.generate_pdf(db, pdf_path, repos=repos)
    reports.print_statistics(db, repos=repos)
    db.close()

    # Derive the tagged classification DB from the operational DB (spec Step 4a).
    stats = sub_db.build_classification_db(config.DB_PATH, config.CLASSIFICATION_DB_PATH)
    print(f"\n  Classification DB → {config.CLASSIFICATION_DB_PATH}")
    for k, v in stats.items():
        print(f"     {k:20s}: {v}")
    print(f"  XLSX → {xlsx_path}")
    print(f"  PDF  → {pdf_path}")


def main():
    parser = argparse.ArgumentParser(
        description="QDArchive Seeding Pipeline — discover and download qualitative research data"
    )
    parser.add_argument(
        "--repos", nargs="*", default=None,
        help=f"Repository keys to process. Available: {', '.join(config.REPOSITORIES.keys())}",
    )
    parser.add_argument(
        "--queries", nargs="*", default=None,
        help="Custom search queries (overrides defaults)",
    )
    parser.add_argument(
        "--harvest-only", action="store_true",
        help="Only harvest metadata — do not download files",
    )
    parser.add_argument(
        "--qda-only", action="store_true",
        help="Only download projects that contain QDA (analysis) files",
    )
    parser.add_argument(
        "--fresh", action="store_true",
        help="Clear any saved progress and start harvest from scratch",
    )
    parser.add_argument(
        "--classify", action="store_true",
        help="Run Phase 2 classification + deliverables after the acquisition pipeline",
    )
    parser.add_argument(
        "--classify-only", action="store_true",
        help="Only run Phase 2 classification + deliverables on the existing database",
    )
    parser.add_argument(
        "--log-level", default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging verbosity (default: INFO)",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    if args.classify_only:
        _run_classification_phase(args.repos)
        print("\n  Classification complete!")
        return

    summary = run_full_pipeline(
        repos=args.repos,
        queries=args.queries,
        download=not args.harvest_only,
        only_qda=args.qda_only,
        fresh=args.fresh,
    )

    print("\n  Pipeline complete!")
    print(f"   Projects discovered : {summary['total_projects']}")
    print(f"   With QDA files      : {summary['projects_with_qda']}")
    print(f"   QDA files (total)   : {summary['total_qda_files']}")
    print(f"     .qdpx files       : {summary['total_qdpx_files']}")
    print(f"     MAXQDA files      : {summary['total_maxqda_files']}")
    print(f"   Downloaded          : {summary['downloaded_projects']}")
    print(f"   Files cataloged     : {summary['total_files']}")
    print(f"   Challenges logged   : {summary['technical_challenges']}")

    if args.classify:
        _run_classification_phase(args.repos)


if __name__ == "__main__":
    main()
