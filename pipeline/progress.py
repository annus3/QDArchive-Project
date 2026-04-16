"""
Minimal progress/resume tracker for the harvest pipeline.

Persists pagination state to a JSON file so that interrupted harvests
can resume from where they left off instead of re-fetching everything.
"""

import json
import logging
import os
from datetime import datetime, timezone

from . import config

logger = logging.getLogger(__name__)


class ProgressTracker:

    def __init__(self, path: str | None = None):
        self.path = path or config.PROGRESS_FILE
        self.state = self._load()


    # Persistence
    def _load(self) -> dict:
        """Load progress from disk; handle corruption gracefully."""
        if not os.path.exists(self.path):
            return self._fresh_state()
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict) or data.get("version") != 1:
                raise ValueError("unexpected format")
            return data
        except (json.JSONDecodeError, ValueError, KeyError) as exc:
            corrupt_path = self.path + ".corrupt"
            logger.warning("Progress file corrupt (%s) — renaming to %s and starting fresh",
                           exc, corrupt_path)
            os.replace(self.path, corrupt_path)
            return self._fresh_state()

    @staticmethod
    def _fresh_state() -> dict:
        return {
            "version": 1,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "harvesters": {},
        }

    def save(self):
        """Atomic write via tmp + os.replace()."""
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.state, f, indent=2, ensure_ascii=False)
        os.replace(tmp, self.path)


    # Query-level tracking
    def _harvester(self, repo_key: str) -> dict:
        h = self.state.setdefault("harvesters", {})
        return h.setdefault(repo_key, {
            "completed_queries": {},
            "offsets": {},
        })

    def get_offset(self, repo_key: str, phase: str, query: str) -> int:
        """Return saved pagination offset, or 0."""
        h = self._harvester(repo_key)
        key = f"{phase}:{query}"
        return h.get("offsets", {}).get(key, 0)

    def save_offset(self, repo_key: str, phase: str, query: str, offset: int):
        """Persist current pagination offset."""
        h = self._harvester(repo_key)
        h.setdefault("offsets", {})[f"{phase}:{query}"] = offset
        self.save()

    def is_query_complete(self, repo_key: str, phase: str, query: str) -> bool:
        """Check if a query was fully paginated in a previous run."""
        h = self._harvester(repo_key)
        completed = h.get("completed_queries", {}).get(phase, [])
        return query in completed

    def mark_query_complete(self, repo_key: str, phase: str, query: str):
        """Mark a query as done and clear its offset."""
        h = self._harvester(repo_key)
        h.setdefault("completed_queries", {}).setdefault(phase, [])
        if query not in h["completed_queries"][phase]:
            h["completed_queries"][phase].append(query)
        # Clear offset — no longer needed
        h.get("offsets", {}).pop(f"{phase}:{query}", None)
        self.save()


    # Lifecycle
    def clear(self, repo_key: str | None = None):
        """Clear progress state for a repo or all repos."""
        if repo_key:
            self.state.get("harvesters", {}).pop(repo_key, None)
        else:
            self.state = self._fresh_state()
        self.save()

    def is_stale(self, max_age_hours: int = 72) -> bool:
        """Detect progress from a previous run that's too old."""
        started = self.state.get("started_at", "")
        if not started:
            return False
        try:
            started_dt = datetime.fromisoformat(started)
            age = datetime.now(timezone.utc) - started_dt
            return age.total_seconds() > max_age_hours * 3600
        except (ValueError, TypeError):
            return True
