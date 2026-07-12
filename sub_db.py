#!/usr/bin/env python3
"""
sub_db.py 

Usage:
    python sub_db.py                    # build the submission DB
    python sub_db.py --classification   # build the classification DB instead
"""

import argparse
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from pipeline import config


DOWNLOAD_RESULT = {
    "SUCCEEDED",
    "FAILED_SERVER_UNRESPONSIVE",
    "FAILED_LOGIN_REQUIRED",
    "FAILED_TOO_LARGE",
}
PERSON_ROLE_ENUM = {"UPLOADER", "AUTHOR", "OWNER", "OTHER", "UNKNOWN"}
LICENSE_ENUM = {
    "CC BY", "CC BY-SA", "CC BY-NC", "CC BY-ND", "CC BY-NC-ND",
    "CC0", "ODbL", "ODC-By", "PDDL", "ODbL-1.0", "ODC-By-1.0",
}


def _normalize_license(value: str) -> str | None:
    if not value:
        return None
    v = value.strip()
    if not v:
        return None
    if v in LICENSE_ENUM:
        return v
    lower = v.lower()
    if lower.startswith("cc0"):
        return "CC0"
    if lower.startswith("cc by-nc-nd"):
        return "CC BY-NC-ND"
    if lower.startswith("cc by-nc-sa"):
        return None
    if lower.startswith("cc by-nc"):
        return "CC BY-NC"
    if lower.startswith("cc by-sa"):
        return "CC BY-SA"
    if lower.startswith("cc by-nd"):
        return "CC BY-ND"
    if lower.startswith("cc by"):
        return "CC BY"
    return None


def _normalize_person_role(role: str) -> str:
    if not role:
        return "UNKNOWN"
    r = role.strip().upper()
    if r in PERSON_ROLE_ENUM:
        return r
    # Any non-enum value (e.g. "CONTACT") becomes "OTHER"
    return "OTHER"


def _normalize_download_result(status: str) -> str:
    if status in DOWNLOAD_RESULT:
        return status
    # Legacy lowercase values that may still exist on older DBs
    alias = {
        "downloaded": "SUCCEEDED",
        "skipped": "FAILED_TOO_LARGE",
        "failed": "FAILED_SERVER_UNRESPONSIVE",
        "pending": "FAILED_SERVER_UNRESPONSIVE",
    }
    return alias.get(status, "FAILED_SERVER_UNRESPONSIVE")


# Schema --------------------------------------------------------------------
SUBMISSION_SCHEMA = """
CREATE TABLE projects (
    id                         INTEGER PRIMARY KEY,
    query_string               TEXT,
    repository_id              INTEGER NOT NULL,
    repository_url             TEXT    NOT NULL,
    project_url                TEXT    NOT NULL,
    version                    TEXT,
    title                      TEXT    NOT NULL,
    description                TEXT    NOT NULL,
    language                   TEXT,
    doi                        TEXT,
    upload_date                TEXT,
    download_date              TEXT    NOT NULL,
    download_repository_folder TEXT    NOT NULL,
    download_project_folder    TEXT    NOT NULL,
    download_version_folder    TEXT,
    download_method            TEXT    NOT NULL
);

CREATE TABLE files (
    id         INTEGER PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES projects(id),
    file_name  TEXT    NOT NULL,
    file_type  TEXT    NOT NULL,
    status     TEXT    NOT NULL
);

CREATE TABLE keywords (
    id         INTEGER PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES projects(id),
    keyword    TEXT    NOT NULL
);

CREATE TABLE person_role (
    id         INTEGER PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES projects(id),
    name       TEXT    NOT NULL,
    role       TEXT    NOT NULL
);

CREATE TABLE licenses (
    id         INTEGER PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES projects(id),
    license    TEXT    NOT NULL
);
"""


def build_submission_db(src_path: str, dst_path: str) -> dict:
    if not os.path.exists(src_path):
        raise FileNotFoundError(f"Operational DB not found: {src_path}")

    if os.path.exists(dst_path):
        os.remove(dst_path)
    # Clean up stale WAL/SHM for the target file if they exist
    for suffix in ("-wal", "-shm", "-journal"):
        p = dst_path + suffix
        if os.path.exists(p):
            os.remove(p)

    src = sqlite3.connect(src_path)
    src.row_factory = sqlite3.Row
    dst = sqlite3.connect(dst_path)
    dst.executescript(SUBMISSION_SCHEMA)

    stats = {
        "projects": 0,
        "files": 0,
        "keywords": 0,
        "person_role": 0,
        "licenses": 0,
        "licenses_dropped": 0,
    }

    # Projects -------------------------------------------------------------
    proj_rows = src.execute("""
        SELECT id,
               query_string,
               repository_id,
               repository_url,
               COALESCE(project_url, source_url) AS project_url,
               version,
               title,
               description,
               language,
               doi,
               COALESCE(upload_date, publication_date) AS upload_date,
               download_date,
               download_repository_folder,
               download_project_folder,
               download_version_folder,
               download_method
        FROM projects
    """).fetchall()

    for r in proj_rows:
        # Required NOT NULL fields — fill with safe defaults if missing so the
        # row is accepted. download_date: use updated_at/created_at if absent.
        download_date = r["download_date"] or ""
        if not download_date:
            cur = src.execute(
                "SELECT COALESCE(updated_at, created_at, '') FROM projects WHERE id=?",
                (r["id"],),
            ).fetchone()
            download_date = cur[0] if cur else ""

        dst.execute(
            """INSERT INTO projects
               (id, query_string, repository_id, repository_url, project_url,
                version, title, description, language, doi, upload_date,
                download_date, download_repository_folder,
                download_project_folder, download_version_folder,
                download_method)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                r["id"],
                r["query_string"],
                r["repository_id"],
                r["repository_url"] or "",
                r["project_url"] or "",
                r["version"],
                r["title"] or "",
                r["description"] or "",
                r["language"],
                r["doi"],
                r["upload_date"],
                download_date,
                r["download_repository_folder"] or "",
                r["download_project_folder"] or "",
                r["download_version_folder"],
                r["download_method"] or "API-CALL",
            ),
        )
        stats["projects"] += 1

    # Files ----------------------------------------------------------------
    file_rows = src.execute(
        "SELECT id, project_id, file_name, file_type, status FROM files"
    ).fetchall()
    for r in file_rows:
        ext = r["file_type"] or ""
        dst.execute(
            "INSERT INTO files (id, project_id, file_name, file_type, status) "
            "VALUES (?,?,?,?,?)",
            (
                r["id"],
                r["project_id"],
                r["file_name"] or "",
                ext,
                _normalize_download_result(r["status"]),
            ),
        )
        stats["files"] += 1

    # Keywords -------------------------------------------------------------
    for r in src.execute(
        "SELECT id, project_id, keyword FROM keywords WHERE keyword IS NOT NULL AND keyword != ''"
    ):
        dst.execute(
            "INSERT INTO keywords (id, project_id, keyword) VALUES (?,?,?)",
            (r["id"], r["project_id"], r["keyword"]),
        )
        stats["keywords"] += 1

    # Person/Role ---------------------------------------------------------
    for r in src.execute(
        "SELECT id, project_id, name, role FROM person_role WHERE name IS NOT NULL AND name != ''"
    ):
        dst.execute(
            "INSERT INTO person_role (id, project_id, name, role) VALUES (?,?,?,?)",
            (r["id"], r["project_id"], r["name"], _normalize_person_role(r["role"])),
        )
        stats["person_role"] += 1

    # Licenses (drop rows whose license does not map to the enum) ---------
    for r in src.execute(
        "SELECT id, project_id, license FROM licenses WHERE license IS NOT NULL AND license != ''"
    ):
        normalized = _normalize_license(r["license"])
        if normalized is None:
            stats["licenses_dropped"] += 1
            continue
        dst.execute(
            "INSERT INTO licenses (id, project_id, license) VALUES (?,?,?)",
            (r["id"], r["project_id"], normalized),
        )
        stats["licenses"] += 1

    dst.commit()
    dst.close()
    src.close()
    return stats


# Classification DB (Phase 2, spec Step 4a) ---------------------------------
# The classification database is the submission schema PLUS the Phase 2
# classification columns. It is built by reusing build_submission_db() untouched
# and then augmenting the copy with the classification columns/values from the
# operational DB (so there is no duplicated copy/normalization logic).
_CLASS_PROJECT_COLS = [
    ("type", "TEXT"),
    ("primary_class", "TEXT"),
    ("secondary_class", "TEXT"),
    ("classification_confidence", "REAL"),
    ("tags", "TEXT"),
]
_CLASS_FILE_COLS = [
    ("primary_class", "TEXT"),
    ("secondary_class", "TEXT"),
    ("classification_confidence", "REAL"),
]


def build_classification_db(src_path: str, dst_path: str) -> dict:
    """Build the classification DB = submission schema + classification columns."""
    stats = build_submission_db(src_path, dst_path)

    src = sqlite3.connect(src_path)
    src.row_factory = sqlite3.Row
    dst = sqlite3.connect(dst_path)

    for col, typedef in _CLASS_PROJECT_COLS:
        dst.execute(f"ALTER TABLE projects ADD COLUMN {col} {typedef}")
    for col, typedef in _CLASS_FILE_COLS:
        dst.execute(f"ALTER TABLE files ADD COLUMN {col} {typedef}")

    proj_classified = 0
    for r in src.execute(
        "SELECT id, type, primary_class, secondary_class, "
        "classification_confidence, tags FROM projects"
    ):
        dst.execute(
            "UPDATE projects SET type=?, primary_class=?, secondary_class=?, "
            "classification_confidence=?, tags=? WHERE id=?",
            (r["type"], r["primary_class"], r["secondary_class"],
             r["classification_confidence"], r["tags"], r["id"]),
        )
        if r["primary_class"]:
            proj_classified += 1

    file_classified = 0
    for r in src.execute(
        "SELECT id, primary_class, secondary_class, classification_confidence FROM files"
    ):
        dst.execute(
            "UPDATE files SET primary_class=?, secondary_class=?, "
            "classification_confidence=? WHERE id=?",
            (r["primary_class"], r["secondary_class"],
             r["classification_confidence"], r["id"]),
        )
        if r["primary_class"]:
            file_classified += 1

    dst.commit()
    dst.close()
    src.close()
    stats["projects_classified"] = proj_classified
    stats["files_classified"] = file_classified
    return stats


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=config.DB_PATH,
                    help="Operational DB path (default: %(default)s)")
    ap.add_argument("--dst", default=None,
                    help="Output DB path (default: submission or classification path)")
    ap.add_argument("--classification", action="store_true",
                    help="Build the classification DB (submission schema + "
                         "classification columns) instead of the submission DB")
    args = ap.parse_args()

    if args.classification:
        dst = args.dst or config.CLASSIFICATION_DB_PATH
        stats = build_classification_db(args.src, dst)
        print(f"Built classification DB → {dst}")
    else:
        dst = args.dst or config.SUBMISSION_DB_PATH
        stats = build_submission_db(args.src, dst)
        print(f"Built submission DB → {dst}")
    for k, v in stats.items():
        print(f"  {k:20s} {v}")


if __name__ == "__main__":
    main()

