#!/usr/bin/env python3
"""
export_csv.py — Export the QDArchive database to CSV files.

Usage:
    python export_csv.py                    # Export per-repo + combined
    python export_csv.py --repo harvard_dataverse   # Single repo only
    python export_csv.py --output ./my_dir  # Custom output directory
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from pipeline.database import Database
from pipeline import config

# Assigned repositories
ASSIGNED_REPOS = ["harvard_dataverse", "columbia_oral_history"]


def _export_for_repo(db: Database, repo_key: str, base_dir: str):
    """Export CSVs for a single repository into its own subdirectory."""
    repo_dir = os.path.join(base_dir, repo_key)
    os.makedirs(repo_dir, exist_ok=True)

    p = db.export_projects_csv(os.path.join(repo_dir, "projects.csv"), source_repository=repo_key)
    f = db.export_files_csv(os.path.join(repo_dir, "files.csv"), source_repository=repo_key)
    c = db.export_challenges_csv(os.path.join(repo_dir, "technical_challenges.csv"), source_repository=repo_key)

    summary = db.summary(source_repository=repo_key)
    print(f"\n  [{repo_key}]")
    print(f"    projects.csv             → {p}")
    print(f"    files.csv                → {f}")
    print(f"    technical_challenges.csv → {c}")
    print(f"    {summary['total_projects']} projects, {summary['total_files']} files, "
          f"{summary['projects_with_qda']} with QDA")
    print(f"    QDA files: {summary['total_qda_files']} total "
          f"({summary['total_qdpx_files']} .qdpx, {summary['total_maxqda_files']} MAXQDA)")


def _export_combined(db: Database, base_dir: str):
    """Export combined CSVs for all repositories."""
    combined_dir = os.path.join(base_dir, "combined")
    os.makedirs(combined_dir, exist_ok=True)

    p = db.export_projects_csv(os.path.join(combined_dir, "projects.csv"))
    f = db.export_files_csv(os.path.join(combined_dir, "files.csv"))
    c = db.export_challenges_csv(os.path.join(combined_dir, "technical_challenges.csv"))

    summary = db.summary()
    print(f"\n  [combined]")
    print(f"    projects.csv             → {p}")
    print(f"    files.csv                → {f}")
    print(f"    technical_challenges.csv → {c}")
    print(f"    {summary['total_projects']} projects, {summary['total_files']} files, "
          f"{summary['projects_with_qda']} with QDA")
    print(f"    QDA files: {summary['total_qda_files']} total "
          f"({summary['total_qdpx_files']} .qdpx, {summary['total_maxqda_files']} MAXQDA)")


def main():
    parser = argparse.ArgumentParser(description="Export QDArchive database to CSV")
    parser.add_argument(
        "--output", default=config.EXPORTS_DIR,
        help=f"Output directory (default: {config.EXPORTS_DIR})",
    )
    parser.add_argument(
        "--db", default=config.DB_PATH,
        help=f"Database path (default: {config.DB_PATH})",
    )
    parser.add_argument(
        "--repo", default=None,
        help="Export only a specific repository (e.g. harvard_dataverse)",
    )
    args = parser.parse_args()

    if not os.path.exists(args.db):
        print(f"Database not found at {args.db}. Run the pipeline first.")
        sys.exit(1)

    db = Database(args.db)

    if args.repo:
        _export_for_repo(db, args.repo, args.output)
    else:
        # Export each assigned repo separately + combined
        for repo_key in ASSIGNED_REPOS:
            _export_for_repo(db, repo_key, args.output)
        _export_combined(db, args.output)

    db.close()


if __name__ == "__main__":
    main()
