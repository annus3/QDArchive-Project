"""
SQLite database layer — schema, CRUD operations, CSV export.

The schema is designed to evolve; fields that cannot be filled are left NULL.
"""

import csv
import json
import os
import sqlite3
from datetime import datetime, timezone

from . import config


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class Database:
    """Thin wrapper around an SQLite database for the QDArchive pipeline."""

    def __init__(self, db_path: str | None = None):
        self.db_path = db_path or config.DB_PATH
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self._pending_ops = 0
        self._create_tables()

    
    # Schema
    
    def _create_tables(self):
        self.conn.executescript("""
        CREATE TABLE IF NOT EXISTS projects (
            id                 INTEGER PRIMARY KEY AUTOINCREMENT,
            source_repository  TEXT,          -- e.g. "harvard_dataverse", "columbia_oral_history"
            source_name        TEXT,          -- Human-readable repo name
            source_url         TEXT,          -- Direct URL to the project page
            source_id          TEXT,          -- Repository-specific identifier
            title              TEXT,
            authors            TEXT,          -- JSON array
            description        TEXT,
            license            TEXT,
            license_url        TEXT,
            doi                TEXT,
            publication_date   TEXT,
            keywords           TEXT,          -- JSON array
            project_scope      TEXT,          -- Qualitative research area / topic
            has_qda_files      INTEGER DEFAULT 0,  -- Boolean 0/1
            qda_file_count     INTEGER DEFAULT 0,  -- Total QDA files (all formats)
            qdpx_file_count    INTEGER DEFAULT 0,  -- .qdpx files (REFI-QDA standard)
            maxqda_file_count  INTEGER DEFAULT 0,  -- MAXQDA files (.mx24/.mx22/.mx20/…)
            metadata_json      TEXT,          -- Full raw API metadata
            download_status    TEXT DEFAULT 'pending',  -- pending | downloaded | failed | skipped
            download_date      TEXT,
            notes              TEXT,
            created_at         TEXT,
            updated_at         TEXT,
            UNIQUE(source_repository, source_id)
        );

        CREATE TABLE IF NOT EXISTS files (
            id                 INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id         INTEGER NOT NULL REFERENCES projects(id),
            file_name          TEXT,                     -- required schema
            file_extension     TEXT,
            file_type          TEXT,                     -- extension without dot (e.g. "xlsx") — required schema
            file_category      TEXT DEFAULT 'unknown',   -- analysis | primary | additional | unknown
            file_size_bytes    INTEGER,
            download_url       TEXT,
            local_path         TEXT,
            checksum           TEXT,
            status             TEXT DEFAULT 'FAILED_SERVER_UNRESPONSIVE',  -- DOWNLOAD_RESULT enum
            downloaded_at      TEXT,
            created_at         TEXT
        );

        CREATE TABLE IF NOT EXISTS keywords (
            id                 INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id         INTEGER NOT NULL REFERENCES projects(id),
            keyword            TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS person_role (
            id                 INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id         INTEGER NOT NULL REFERENCES projects(id),
            name               TEXT NOT NULL,
            role               TEXT NOT NULL DEFAULT 'UNKNOWN'  -- AUTHOR | CONTACT | UNKNOWN
        );

        CREATE TABLE IF NOT EXISTS licenses (
            id                 INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id         INTEGER NOT NULL REFERENCES projects(id),
            license            TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS technical_challenges (
            id                 INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id         INTEGER REFERENCES projects(id),
            source_repository  TEXT,
            challenge_type     TEXT,   -- access_denied | rate_limit | corrupt_file | missing_metadata | large_file | api_error | other
            description        TEXT,
            created_at         TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_projects_source ON projects(source_repository, source_id);
        CREATE INDEX IF NOT EXISTS idx_files_project   ON files(project_id);
        CREATE INDEX IF NOT EXISTS idx_keywords_project ON keywords(project_id);
        CREATE INDEX IF NOT EXISTS idx_person_role_project ON person_role(project_id);
        CREATE INDEX IF NOT EXISTS idx_licenses_project ON licenses(project_id);
        """)
        self.conn.commit()
        self._migrate()

    def _migrate(self):
        """Add columns that may not exist in older databases."""
        existing = {r[1] for r in self.conn.execute("PRAGMA table_info(projects)")}
        project_migrations = [
            ("qda_file_count", "INTEGER DEFAULT 0"),
            ("qdpx_file_count", "INTEGER DEFAULT 0"),
            ("maxqda_file_count", "INTEGER DEFAULT 0"),
            ("download_method", "TEXT"),
            ("matched_queries", "TEXT DEFAULT '[]'"),
            # Required schema fields
            ("query_string", "TEXT"),
            ("repository_id", "INTEGER"),
            ("repository_url", "TEXT"),
            ("project_url", "TEXT"),
            ("version", "TEXT"),
            ("language", "TEXT"),
            ("upload_date", "TEXT"),
            ("download_repository_folder", "TEXT"),
            ("download_project_folder", "TEXT"),
            ("download_version_folder", "TEXT"),
        ]
        for col, typedef in project_migrations:
            if col not in existing:
                self.conn.execute(f"ALTER TABLE projects ADD COLUMN {col} {typedef}")

        # Files table migrations
        file_cols = {r[1] for r in self.conn.execute("PRAGMA table_info(files)")}
        file_migrations = [
            ("file_type", "TEXT"),
            ("file_category", "TEXT DEFAULT 'unknown'"),
        ]
        for col, typedef in file_migrations:
            if col not in file_cols:
                self.conn.execute(f"ALTER TABLE files ADD COLUMN {col} {typedef}")

        # Rename legacy columns to sq26-grading required names
        file_cols = {r[1] for r in self.conn.execute("PRAGMA table_info(files)")}
        if "filename" in file_cols and "file_name" not in file_cols:
            self.conn.execute("ALTER TABLE files RENAME COLUMN filename TO file_name")
        if "download_status" in file_cols and "status" not in file_cols:
            self.conn.execute("ALTER TABLE files RENAME COLUMN download_status TO status")
        self.conn.commit()

        # Remap legacy file status values to DOWNLOAD_RESULT enum
        self.conn.execute(
            "UPDATE files SET status='SUCCEEDED' WHERE status='downloaded'"
        )
        self.conn.execute(
            "UPDATE files SET status='FAILED_TOO_LARGE' WHERE status='skipped'"
        )
        self.conn.execute(
            "UPDATE files SET status='FAILED_SERVER_UNRESPONSIVE' "
            "WHERE status IN ('failed','pending') OR status IS NULL"
        )

        # Backfill existing rows — projects
        self.conn.execute(
            "UPDATE projects SET download_method='API-CALL' "
            "WHERE download_method IS NULL OR download_method IN ('dataverse_api', 'dlc_json_api')"
        )
        self.conn.execute(
            "UPDATE projects SET matched_queries='[]' WHERE matched_queries IS NULL"
        )
        self.conn.execute(
            "UPDATE projects SET query_string = json_extract(matched_queries, '$[0]') "
            "WHERE query_string IS NULL AND matched_queries != '[]'"
        )
        self.conn.execute(
            "UPDATE projects SET repository_id = 10 "
            "WHERE source_repository = 'harvard_dataverse' AND repository_id IS NULL"
        )
        self.conn.execute(
            "UPDATE projects SET repository_id = 19 "
            "WHERE source_repository = 'columbia_oral_history' AND repository_id IS NULL"
        )
        self.conn.execute(
            "UPDATE projects SET repository_url = 'https://dataverse.harvard.edu' "
            "WHERE source_repository = 'harvard_dataverse' AND repository_url IS NULL"
        )
        self.conn.execute(
            "UPDATE projects SET repository_url = 'https://dlc.library.columbia.edu' "
            "WHERE source_repository = 'columbia_oral_history' AND repository_url IS NULL"
        )
        self.conn.execute(
            "UPDATE projects SET project_url = source_url WHERE project_url IS NULL"
        )
        self.conn.execute(
            "UPDATE projects SET upload_date = publication_date WHERE upload_date IS NULL"
        )
        self.conn.execute(
            "UPDATE projects SET download_repository_folder = source_repository "
            "WHERE download_repository_folder IS NULL"
        )
        self.conn.execute(
            "UPDATE projects SET download_project_folder = source_id "
            "WHERE download_project_folder IS NULL"
        )
        # DOI: convert bare identifiers to full URL format
        self.conn.execute(
            "UPDATE projects SET doi = 'https://doi.org/' || doi "
            "WHERE doi IS NOT NULL AND doi != '' AND doi NOT LIKE 'https://%'"
        )

        # Backfill existing rows — files
        # file_category takes over the old file_type classification values
        self.conn.execute(
            "UPDATE files SET file_category = file_type "
            "WHERE file_category IS NULL OR file_category = 'unknown'"
        )
        # file_type now means extension without dot (per required schema)
        self.conn.execute(
            "UPDATE files SET file_type = REPLACE(file_extension, '.', '') "
            "WHERE file_extension IS NOT NULL AND file_extension != ''"
        )

        self.conn.commit()

        # Populate normalized tables from JSON fields (Python needed for parsing)
        self._backfill_normalized_tables()

    def _backfill_normalized_tables(self):
        """Populate keywords, person_role, licenses from existing JSON fields."""
        # Only backfill if tables are empty (first migration)
        kw_count = self.conn.execute("SELECT COUNT(*) AS c FROM keywords").fetchone()["c"]
        if kw_count > 0:
            return

        rows = self.conn.execute(
            "SELECT id, keywords, authors, license FROM projects"
        ).fetchall()
        for row in rows:
            pid = row["id"]
            # Keywords (deduplicate)
            kw_raw = row["keywords"]
            if kw_raw:
                try:
                    kw_list = json.loads(kw_raw) if isinstance(kw_raw, str) else kw_raw
                    seen_kw = set()
                    if isinstance(kw_list, list):
                        for kw in kw_list:
                            if isinstance(kw, str) and kw.strip() and kw.strip() not in seen_kw:
                                seen_kw.add(kw.strip())
                                self.conn.execute(
                                    "INSERT INTO keywords (project_id, keyword) VALUES (?, ?)",
                                    (pid, kw.strip()),
                                )
                except (json.JSONDecodeError, TypeError):
                    pass
            # Authors → person_role (deduplicate)
            auth_raw = row["authors"]
            if auth_raw:
                try:
                    auth_list = json.loads(auth_raw) if isinstance(auth_raw, str) else auth_raw
                    seen_names = set()
                    if isinstance(auth_list, list):
                        for name in auth_list:
                            if isinstance(name, str) and name.strip() and name.strip() not in seen_names:
                                seen_names.add(name.strip())
                                self.conn.execute(
                                    "INSERT INTO person_role (project_id, name, role) VALUES (?, ?, ?)",
                                    (pid, name.strip(), "AUTHOR"),
                                )
                except (json.JSONDecodeError, TypeError):
                    pass
            # License → licenses
            lic = row["license"]
            if lic and isinstance(lic, str) and lic.strip():
                self.conn.execute(
                    "INSERT INTO licenses (project_id, license) VALUES (?, ?)",
                    (pid, lic.strip()),
                )
        self.conn.commit()


    # Batch commit helpers
    def _maybe_commit(self):
        """Commit every BATCH_COMMIT_SIZE operations to reduce disk flushes."""
        self._pending_ops += 1
        if self._pending_ops >= config.BATCH_COMMIT_SIZE:
            self.conn.commit()
            self._pending_ops = 0

    def flush(self):
        """Force-commit any pending writes."""
        if self._pending_ops > 0:
            self.conn.commit()
            self._pending_ops = 0


    # Projects
    def upsert_project(self, **kwargs) -> int:
        """Insert or update a project. Returns the project id.

        ``matched_queries`` is handled specially: incoming values are *merged*
        (appended + deduplicated) with any existing list, rather than
        overwriting it.
        """
        now = _now_iso()
        kwargs.setdefault("created_at", now)
        kwargs["updated_at"] = now

        # Format DOI as full URL if bare identifier
        doi = kwargs.get("doi")
        if doi and isinstance(doi, str) and doi.strip() and not doi.startswith("https://"):
            kwargs["doi"] = f"https://doi.org/{doi}"

        # Mirror fields for required schema compatibility
        if "source_url" in kwargs and "project_url" not in kwargs:
            kwargs["project_url"] = kwargs["source_url"]
        if "publication_date" in kwargs and "upload_date" not in kwargs:
            kwargs["upload_date"] = kwargs["publication_date"]

        # Extract matched_queries before the upsert (needs merge, not overwrite)
        incoming_queries = kwargs.pop("matched_queries", None)

        # Set query_string to first query if not already set
        if incoming_queries and "query_string" not in kwargs:
            kwargs["query_string"] = incoming_queries[0] if incoming_queries else None

        # Serialize lists/dicts to JSON
        for key in ("authors", "keywords", "metadata_json"):
            val = kwargs.get(key)
            if val is not None and not isinstance(val, str):
                kwargs[key] = json.dumps(val, ensure_ascii=False)

        # Try insert; on conflict update non-key fields
        cols = list(kwargs.keys())
        placeholders = ", ".join(f":{c}" for c in cols)
        updates = ", ".join(
            f"{c}=excluded.{c}" for c in cols
            if c not in ("source_repository", "source_id", "created_at", "query_string")
        )
        sql = f"""
            INSERT INTO projects ({', '.join(cols)})
            VALUES ({placeholders})
            ON CONFLICT(source_repository, source_id) DO UPDATE SET {updates}
        """
        self.conn.execute(sql, kwargs)
        self._maybe_commit()

        # Always use SELECT to get the correct id (lastrowid can be unreliable
        # for INSERT ... ON CONFLICT DO UPDATE in some SQLite versions)
        row = self.conn.execute(
            "SELECT id, matched_queries FROM projects "
            "WHERE source_repository=:source_repository AND source_id=:source_id",
            kwargs,
        ).fetchone()
        project_id = row["id"]

        # Merge matched_queries (append new, deduplicate)
        if incoming_queries:
            existing = json.loads(row["matched_queries"] or "[]")
            merged = existing[:]
            for q in incoming_queries:
                if q not in merged:
                    merged.append(q)
            if merged != existing:
                self.conn.execute(
                    "UPDATE projects SET matched_queries=? WHERE id=?",
                    (json.dumps(merged, ensure_ascii=False), project_id),
                )
                self._maybe_commit()

        return project_id

    def append_matched_query(self, project_id: int, query: str):
        """Append a single query to a project's matched_queries list (if not already present)."""
        row = self.conn.execute(
            "SELECT matched_queries FROM projects WHERE id=?", (project_id,)
        ).fetchone()
        if not row:
            return
        existing = json.loads(row["matched_queries"] or "[]")
        if query not in existing:
            existing.append(query)
            self.conn.execute(
                "UPDATE projects SET matched_queries=? WHERE id=?",
                (json.dumps(existing, ensure_ascii=False), project_id),
            )
            self._maybe_commit()

    def get_project(self, source_repository: str, source_id: str) -> dict | None:
        row = self.conn.execute(
            "SELECT * FROM projects WHERE source_repository=? AND source_id=?",
            (source_repository, source_id),
        ).fetchone()
        return dict(row) if row else None

    def update_project_status(self, project_id: int, status: str):
        now = _now_iso()
        self.conn.execute(
            "UPDATE projects SET download_status=?, download_date=?, updated_at=? WHERE id=?",
            (status, now, now, project_id),
        )
        self.conn.commit()


    # QDA file counts
    def update_qda_counts(self, project_id: int):
        """Recompute QDA file counts for a project from its files table entries."""
        files = self.get_files_for_project(project_id)
        qda_count = 0
        qdpx_count = 0
        maxqda_count = 0
        for f in files:
            ext = (f.get("file_extension") or "").lower()
            if ext in config.QDA_EXTENSIONS:
                qda_count += 1
            if ext == ".qdpx":
                qdpx_count += 1
            if ext in config.MAXQDA_EXTENSIONS:
                maxqda_count += 1
        self.conn.execute(
            """UPDATE projects
               SET has_qda_files=?, qda_file_count=?, qdpx_file_count=?, maxqda_file_count=?,
                   updated_at=?
               WHERE id=?""",
            (1 if qda_count > 0 else 0, qda_count, qdpx_count, maxqda_count,
             _now_iso(), project_id),
        )
        self._maybe_commit()

    def count_projects(self, source_repository: str | None = None) -> int:
        if source_repository:
            row = self.conn.execute(
                "SELECT COUNT(*) AS c FROM projects WHERE source_repository=?",
                (source_repository,),
            ).fetchone()
        else:
            row = self.conn.execute("SELECT COUNT(*) AS c FROM projects").fetchone()
        return row["c"]


    # Files
    def insert_file(self, **kwargs) -> int:
        # Accept legacy "filename" kwarg for backward compatibility with callers
        if "filename" in kwargs and "file_name" not in kwargs:
            kwargs["file_name"] = kwargs.pop("filename")

        # Skip if this file already exists for the project (idempotent re-harvest)
        pid = kwargs.get("project_id")
        fname = kwargs.get("file_name")
        if pid and fname:
            existing = self.conn.execute(
                "SELECT id FROM files WHERE project_id=? AND file_name=?",
                (pid, fname),
            ).fetchone()
            if existing:
                return existing["id"]

        # Map file_type (classification) → file_category for backward compatibility
        if "file_type" in kwargs and "file_category" not in kwargs:
            kwargs["file_category"] = kwargs.pop("file_type")

        # Populate file_type as extension without dot (required schema)
        ext = kwargs.get("file_extension", "")
        if ext and "file_type" not in kwargs:
            kwargs["file_type"] = ext.lstrip(".")

        # Default new rows to the enum "pending-equivalent" (before a download attempt)
        kwargs.setdefault("status", "FAILED_SERVER_UNRESPONSIVE")
        kwargs.setdefault("created_at", _now_iso())
        cols = list(kwargs.keys())
        placeholders = ", ".join(f":{c}" for c in cols)
        sql = f"INSERT INTO files ({', '.join(cols)}) VALUES ({placeholders})"
        cur = self.conn.execute(sql, kwargs)
        self._maybe_commit()
        return cur.lastrowid

    def get_files_for_project(self, project_id: int) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM files WHERE project_id=?", (project_id,)
        ).fetchall()
        return [dict(r) for r in rows]

    # DOWNLOAD_RESULT enum (sq26-grading). Legacy callers may still pass the
    # old lowercase values; map them here so existing code keeps working.
    _STATUS_ALIASES = {
        "downloaded": "SUCCEEDED",
        "failed": "FAILED_SERVER_UNRESPONSIVE",
        "pending": "FAILED_SERVER_UNRESPONSIVE",
        "skipped": "FAILED_TOO_LARGE",
    }

    def update_file_status(self, file_id: int, status: str, local_path: str | None = None):
        now = _now_iso()
        status = self._STATUS_ALIASES.get(status, status)
        if local_path:
            self.conn.execute(
                "UPDATE files SET status=?, local_path=?, downloaded_at=? WHERE id=?",
                (status, local_path, now, file_id),
            )
        else:
            self.conn.execute(
                "UPDATE files SET status=?, downloaded_at=? WHERE id=?",
                (status, now, file_id),
            )
        self.conn.commit()

    # Keywords (normalized table)
    def insert_keyword(self, project_id: int, keyword: str):
        """Insert a keyword for a project (skip duplicates)."""
        if not keyword or not keyword.strip():
            return
        existing = self.conn.execute(
            "SELECT id FROM keywords WHERE project_id=? AND keyword=?",
            (project_id, keyword.strip()),
        ).fetchone()
        if not existing:
            self.conn.execute(
                "INSERT INTO keywords (project_id, keyword) VALUES (?, ?)",
                (project_id, keyword.strip()),
            )
            self._maybe_commit()

    def get_keywords_for_project(self, project_id: int) -> list[str]:
        rows = self.conn.execute(
            "SELECT keyword FROM keywords WHERE project_id=?", (project_id,)
        ).fetchall()
        return [r["keyword"] for r in rows]


    # Person/Role (normalized table)
    def insert_person_role(self, project_id: int, name: str, role: str = "UNKNOWN"):
        """Insert a person+role for a project (skip duplicates by name+role)."""
        if not name or not name.strip():
            return
        existing = self.conn.execute(
            "SELECT id FROM person_role WHERE project_id=? AND name=? AND role=?",
            (project_id, name.strip(), role),
        ).fetchone()
        if not existing:
            self.conn.execute(
                "INSERT INTO person_role (project_id, name, role) VALUES (?, ?, ?)",
                (project_id, name.strip(), role),
            )
            self._maybe_commit()

    def get_persons_for_project(self, project_id: int) -> list[dict]:
        rows = self.conn.execute(
            "SELECT name, role FROM person_role WHERE project_id=?", (project_id,)
        ).fetchall()
        return [dict(r) for r in rows]


        # Licenses (normalized table)
    def insert_license(self, project_id: int, license_str: str):
        """Insert a license for a project (skip duplicates)."""
        if not license_str or not license_str.strip():
            return
        existing = self.conn.execute(
            "SELECT id FROM licenses WHERE project_id=? AND license=?",
            (project_id, license_str.strip()),
        ).fetchone()
        if not existing:
            self.conn.execute(
                "INSERT INTO licenses (project_id, license) VALUES (?, ?)",
                (project_id, license_str.strip()),
            )
            self._maybe_commit()

    def get_licenses_for_project(self, project_id: int) -> list[str]:
        rows = self.conn.execute(
            "SELECT license FROM licenses WHERE project_id=?", (project_id,)
        ).fetchall()
        return [r["license"] for r in rows]


    # Technical Challenges
   
    def log_challenge(self, challenge_type: str, description: str,
                      project_id: int | None = None,
                      source_repository: str | None = None):
        self.conn.execute(
            """INSERT INTO technical_challenges
               (project_id, source_repository, challenge_type, description, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (project_id, source_repository, challenge_type, description, _now_iso()),
        )
        self._maybe_commit()

    def get_challenges(self) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM technical_challenges ORDER BY created_at"
        ).fetchall()
        return [dict(r) for r in rows]


    # CSV Export
    def _write_csv(self, path: str, rows: list) -> str:
        """Write rows (list of sqlite3.Row) to a CSV file."""
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if not rows:
            return path
        cols = rows[0].keys()
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=cols)
            writer.writeheader()
            for r in rows:
                writer.writerow(dict(r))
        return path

    def export_projects_csv(self, path: str | None = None,
                            source_repository: str | None = None) -> str:
        path = path or os.path.join(config.EXPORTS_DIR, "projects.csv")
        if source_repository:
            rows = self.conn.execute(
                "SELECT * FROM projects WHERE source_repository=? ORDER BY id",
                (source_repository,),
            ).fetchall()
        else:
            rows = self.conn.execute("SELECT * FROM projects ORDER BY id").fetchall()
        return self._write_csv(path, rows)

    def export_files_csv(self, path: str | None = None,
                         source_repository: str | None = None) -> str:
        path = path or os.path.join(config.EXPORTS_DIR, "files.csv")
        if source_repository:
            rows = self.conn.execute(
                """SELECT f.* FROM files f
                   JOIN projects p ON f.project_id = p.id
                   WHERE p.source_repository=? ORDER BY f.id""",
                (source_repository,),
            ).fetchall()
        else:
            rows = self.conn.execute("SELECT * FROM files ORDER BY id").fetchall()
        return self._write_csv(path, rows)

    def export_challenges_csv(self, path: str | None = None,
                              source_repository: str | None = None) -> str:
        path = path or os.path.join(config.EXPORTS_DIR, "technical_challenges.csv")
        if source_repository:
            rows = self.conn.execute(
                "SELECT * FROM technical_challenges WHERE source_repository=? ORDER BY id",
                (source_repository,),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM technical_challenges ORDER BY id"
            ).fetchall()
        return self._write_csv(path, rows)

    def export_keywords_csv(self, path: str | None = None,
                            source_repository: str | None = None) -> str:
        path = path or os.path.join(config.EXPORTS_DIR, "keywords.csv")
        if source_repository:
            rows = self.conn.execute(
                """SELECT k.* FROM keywords k
                   JOIN projects p ON k.project_id = p.id
                   WHERE p.source_repository=? ORDER BY k.id""",
                (source_repository,),
            ).fetchall()
        else:
            rows = self.conn.execute("SELECT * FROM keywords ORDER BY id").fetchall()
        return self._write_csv(path, rows)

    def export_person_role_csv(self, path: str | None = None,
                               source_repository: str | None = None) -> str:
        path = path or os.path.join(config.EXPORTS_DIR, "person_role.csv")
        if source_repository:
            rows = self.conn.execute(
                """SELECT pr.* FROM person_role pr
                   JOIN projects p ON pr.project_id = p.id
                   WHERE p.source_repository=? ORDER BY pr.id""",
                (source_repository,),
            ).fetchall()
        else:
            rows = self.conn.execute("SELECT * FROM person_role ORDER BY id").fetchall()
        return self._write_csv(path, rows)

    def export_licenses_csv(self, path: str | None = None,
                            source_repository: str | None = None) -> str:
        path = path or os.path.join(config.EXPORTS_DIR, "licenses.csv")
        if source_repository:
            rows = self.conn.execute(
                """SELECT l.* FROM licenses l
                   JOIN projects p ON l.project_id = p.id
                   WHERE p.source_repository=? ORDER BY l.id""",
                (source_repository,),
            ).fetchall()
        else:
            rows = self.conn.execute("SELECT * FROM licenses ORDER BY id").fetchall()
        return self._write_csv(path, rows)


    # Summary
    def summary(self, source_repository: str | None = None) -> dict:
        def _cnt(sql, params=()):
            return self.conn.execute(sql, params).fetchone()["c"]

        filt = "" if not source_repository else " WHERE source_repository=?"
        p = (source_repository,) if source_repository else ()

        total = _cnt(f"SELECT COUNT(*) AS c FROM projects{filt}", p)
        downloaded = _cnt(
            f"SELECT COUNT(*) AS c FROM projects{filt}"
            + (" AND" if source_repository else " WHERE")
            + " download_status='downloaded'",
            p,
        )
        with_qda = _cnt(
            f"SELECT COUNT(*) AS c FROM projects{filt}"
            + (" AND" if source_repository else " WHERE")
            + " has_qda_files=1",
            p,
        )
        total_qdpx = _cnt(
            f"SELECT COALESCE(SUM(qdpx_file_count),0) AS c FROM projects{filt}", p
        )
        total_maxqda = _cnt(
            f"SELECT COALESCE(SUM(maxqda_file_count),0) AS c FROM projects{filt}", p
        )
        total_qda = _cnt(
            f"SELECT COALESCE(SUM(qda_file_count),0) AS c FROM projects{filt}", p
        )

        if source_repository:
            total_files = _cnt(
                "SELECT COUNT(*) AS c FROM files f JOIN projects p ON f.project_id=p.id "
                "WHERE p.source_repository=?",
                p,
            )
            challenges = _cnt(
                "SELECT COUNT(*) AS c FROM technical_challenges WHERE source_repository=?",
                p,
            )
        else:
            total_files = _cnt("SELECT COUNT(*) AS c FROM files")
            challenges = _cnt("SELECT COUNT(*) AS c FROM technical_challenges")

        return {
            "total_projects": total,
            "downloaded_projects": downloaded,
            "projects_with_qda": with_qda,
            "total_qda_files": total_qda,
            "total_qdpx_files": total_qdpx,
            "total_maxqda_files": total_maxqda,
            "total_files": total_files,
            "technical_challenges": challenges,
        }

    def close(self):
        self.flush()
        self.conn.close()
