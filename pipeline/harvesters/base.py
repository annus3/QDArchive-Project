"""
Abstract base class for all repository harvesters.
"""

import logging
import os
import time
from abc import ABC, abstractmethod

import requests

from .. import config
from ..database import Database

logger = logging.getLogger(__name__)


def classify_file(filename: str) -> str:
    """Classify a file as 'analysis', 'primary', or 'additional' based on extension."""
    ext = os.path.splitext(filename)[1].lower()
    if ext in config.QDA_EXTENSIONS:
        return "analysis"
    if ext in config.PRIMARY_DATA_EXTENSIONS:
        return "primary"
    return "additional"


class BaseHarvester(ABC):
    """
    Base class providing common functionality for all harvesters:
    - HTTP session with retry logic
    - Rate-limiting
    - Database handle
    """

    def __init__(self, repo_key: str, db: Database):
        self.repo_key = repo_key
        self.repo_cfg = config.REPOSITORIES[repo_key]
        self.db = db
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "QDArchive-Seeding-Pipeline/1.0 (research project)",
            "Accept": "application/json",
        })
        self._last_request_time = 0.0

    @property
    def name(self) -> str:
        return self.repo_cfg["name"]

    @property
    def base_url(self) -> str:
        return self.repo_cfg["base_url"].rstrip("/")

    @property
    def rate_limit(self) -> float:
        return self.repo_cfg.get("rate_limit_seconds", 1.0)

    # ------------------------------------------------------------------
    # HTTP helpers with rate-limiting
    # ------------------------------------------------------------------
    def _rate_limit_wait(self):
        elapsed = time.time() - self._last_request_time
        if elapsed < self.rate_limit:
            time.sleep(self.rate_limit - elapsed)

    def get(self, url: str, params: dict | None = None, **kwargs) -> requests.Response:
        self._rate_limit_wait()
        for attempt in range(1, config.MAX_RETRIES + 1):
            try:
                resp = self.session.get(url, params=params,
                                        timeout=config.DOWNLOAD_TIMEOUT_SECONDS, **kwargs)
                self._last_request_time = time.time()
                if resp.status_code == 429:
                    wait = int(resp.headers.get("Retry-After", 60))
                    logger.warning("[%s] Rate-limited (429). Waiting %ds…", self.name, wait)
                    self.db.log_challenge("rate_limit", f"429 on {url}, waiting {wait}s",
                                         source_repository=self.repo_key)
                    time.sleep(wait)
                    continue
                return resp
            except requests.RequestException as exc:
                logger.warning("[%s] Request failed (attempt %d/%d): %s",
                               self.name, attempt, config.MAX_RETRIES, exc)
                if attempt == config.MAX_RETRIES:
                    raise
                time.sleep(2 ** attempt)
        raise RuntimeError("Unreachable")

    # ------------------------------------------------------------------
    # Interface each harvester must implement
    # ------------------------------------------------------------------
    @abstractmethod
    def harvest(self, queries: list[str] | None = None):
        """Search the repository for qualitative data projects and store metadata + file info in the DB."""

    @abstractmethod
    def download_project_files(self, project_id: int):
        """Download all files for a given project from the repository."""
