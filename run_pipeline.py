#!/usr/bin/env python3
"""
run_pipeline.py — Entry point for the QDArchive acquisition pipeline.

Usage:
    python run_pipeline.py                          # Full pipeline (harvest + download all repos)
    python run_pipeline.py --harvest-only           # Only collect metadata, no downloads
    python run_pipeline.py --repos harvard_dataverse columbia_oral_history
    python run_pipeline.py --qda-only               # Only download projects that have QDA files
    python run_pipeline.py --queries "qdpx" "NVivo" # Custom search queries
"""

import argparse
import logging
import sys
import os

# Ensure project root is on the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from pipeline.orchestrator import run_full_pipeline
from pipeline import config


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

    summary = run_full_pipeline(
        repos=args.repos,
        queries=args.queries,
        download=not args.harvest_only,
        only_qda=args.qda_only,
    )

    print("\n✅ Pipeline complete!")
    print(f"   Projects discovered : {summary['total_projects']}")
    print(f"   With QDA files      : {summary['projects_with_qda']}")
    print(f"   QDA files (total)   : {summary['total_qda_files']}")
    print(f"     .qdpx files       : {summary['total_qdpx_files']}")
    print(f"     MAXQDA files      : {summary['total_maxqda_files']}")
    print(f"   Downloaded          : {summary['downloaded_projects']}")
    print(f"   Files cataloged     : {summary['total_files']}")
    print(f"   Challenges logged   : {summary['technical_challenges']}")


if __name__ == "__main__":
    main()
