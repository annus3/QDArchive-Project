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
        self._create_tables()

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------
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
            filename           TEXT,
            file_extension     TEXT,
            file_type          TEXT DEFAULT 'unknown',  -- analysis | primary | additional | unknown
            file_size_bytes    INTEGER,
            download_url       TEXT,
            local_path         TEXT,
            checksum           TEXT,
            download_status    TEXT DEFAULT 'pending',  -- pending | downloaded | failed | skipped
            downloaded_at      TEXT,
            created_at         TEXT
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
        """)
        self.conn.commit()
        self._migrate()

    def _migrate(self):
        """Add columns that may not exist in older databases."""
        existing = {r[1] for r in self.conn.execute("PRAGMA table_info(projects)")}
        migrations = [
            ("qda_file_count", "INTEGER DEFAULT 0"),
            ("qdpx_file_count", "INTEGER DEFAULT 0"),
            ("maxqda_file_count", "INTEGER DEFAULT 0"),
        ]
        for col, typedef in migrations:
            if col not in existing:
                self.conn.execute(f"ALTER TABLE projects ADD COLUMN {col} {typedef}")
        self.conn.commit()

    # ------------------------------------------------------------------
    # Projects
    # ------------------------------------------------------------------
    def upsert_project(self, **kwargs) -> int:
        """Insert or update a project. Returns the project id."""
        now = _now_iso()
        kwargs.setdefault("created_at", now)
        kwargs["updated_at"] = now

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
            if c not in ("source_repository", "source_id", "created_at")
        )
        sql = f"""
            INSERT INTO projects ({', '.join(cols)})
            VALUES ({placeholders})
            ON CONFLICT(source_repository, source_id) DO UPDATE SET {updates}
        """
        cur = self.conn.execute(sql, kwargs)
        self.conn.commit()

        # Always use SELECT to get the correct id (lastrowid can be unreliable
        # for INSERT ... ON CONFLICT DO UPDATE in some SQLite versions)
        row = self.conn.execute(
            "SELECT id FROM projects WHERE source_repository=:source_repository AND source_id=:source_id",
            kwargs,
        ).fetchone()
        return row["id"]

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

    # ------------------------------------------------------------------
    # QDA file counts
    # ------------------------------------------------------------------
    MAXQDA_EXTENSIONS = {'.mx24', '.mx22', '.mx20', '.mx18', '.mx12', '.mex'}

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
            if ext in self.MAXQDA_EXTENSIONS:
                maxqda_count += 1
        self.conn.execute(
            """UPDATE projects
               SET has_qda_files=?, qda_file_count=?, qdpx_file_count=?, maxqda_file_count=?,
                   updated_at=?
               WHERE id=?""",
            (1 if qda_count > 0 else 0, qda_count, qdpx_count, maxqda_count,
             _now_iso(), project_id),
        )
        self.conn.commit()

    def count_projects(self, source_repository: str | None = None) -> int:
        if source_repository:
            row = self.conn.execute(
                "SELECT COUNT(*) AS c FROM projects WHERE source_repository=?",
                (source_repository,),
            ).fetchone()
        else:
            row = self.conn.execute("SELECT COUNT(*) AS c FROM projects").fetchone()
        return row["c"]

    # ------------------------------------------------------------------
    # Files
    # ------------------------------------------------------------------
    def insert_file(self, **kwargs) -> int:
        # Skip if this file already exists for the project (idempotent re-harvest)
        pid = kwargs.get("project_id")
        fname = kwargs.get("filename")
        if pid and fname:
            existing = self.conn.execute(
                "SELECT id FROM files WHERE project_id=? AND filename=?",
                (pid, fname),
            ).fetchone()
            if existing:
                return existing["id"]

        kwargs.setdefault("created_at", _now_iso())
        cols = list(kwargs.keys())
        placeholders = ", ".join(f":{c}" for c in cols)
        sql = f"INSERT INTO files ({', '.join(cols)}) VALUES ({placeholders})"
        cur = self.conn.execute(sql, kwargs)
        self.conn.commit()
        return cur.lastrowid

    def get_files_for_project(self, project_id: int) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM files WHERE project_id=?", (project_id,)
        ).fetchall()
        return [dict(r) for r in rows]

    def update_file_status(self, file_id: int, status: str, local_path: str | None = None):
        now = _now_iso()
        if local_path:
            self.conn.execute(
                "UPDATE files SET download_status=?, local_path=?, downloaded_at=? WHERE id=?",
                (status, local_path, now, file_id),
            )
        else:
            self.conn.execute(
                "UPDATE files SET download_status=?, downloaded_at=? WHERE id=?",
                (status, now, file_id),
            )
        self.conn.commit()

    # ------------------------------------------------------------------
    # Technical Challenges
    # ------------------------------------------------------------------
    def log_challenge(self, challenge_type: str, description: str,
                      project_id: int | None = None,
                      source_repository: str | None = None):
        self.conn.execute(
            """INSERT INTO technical_challenges
               (project_id, source_repository, challenge_type, description, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (project_id, source_repository, challenge_type, description, _now_iso()),
        )
        self.conn.commit()

    def get_challenges(self) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM technical_challenges ORDER BY created_at"
        ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # CSV Export
    # ------------------------------------------------------------------
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

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
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
        self.conn.close()
