"""
Generic Dataverse harvester — works with any Dataverse installation.
Currently configured for Harvard Dataverse (Dataset 10).
API docs: https://guides.dataverse.org/en/latest/api/search.html
"""

import json
import logging
import os

from .. import config
from ..database import Database
from .base import BaseHarvester, classify_file

logger = logging.getLogger(__name__)


class DataverseHarvester(BaseHarvester):

    def __init__(self, db: Database, repo_key: str):
        super().__init__(repo_key, db)

    # ------------------------------------------------------------------
    # Harvest
    # ------------------------------------------------------------------
    def harvest(self, queries: list[str] | None = None):
        queries = queries or config.SEARCH_QUERIES
        seen_ids: set[str] = set()

        for query in queries:
            logger.info("[%s] Searching: %s", self.name, query)
            start = 0
            per_page = 100

            while True:
                resp = self.get(
                    f"{self.base_url}/api/search",
                    params={
                        "q": query,
                        "type": "dataset",
                        "start": start,
                        "per_page": per_page,
                    },
                )
                if resp.status_code != 200:
                    logger.warning("[%s] Search returned %d for '%s'",
                                   self.name, resp.status_code, query)
                    self.db.log_challenge(
                        "api_error",
                        f"Search HTTP {resp.status_code} for '{query}' at {self.base_url}",
                        source_repository=self.repo_key,
                    )
                    break

                body = resp.json()
                data = body.get("data", body)
                items = data.get("items", [])
                total = data.get("total_count", 0)

                if not items:
                    break

                for item in items:
                    global_id = item.get("global_id", "")
                    if not global_id or global_id in seen_ids:
                        continue
                    seen_ids.add(global_id)
                    self._process_item(item)

                logger.info("[%s] Offset %d — fetched %d items (total: %d, collected: %d)",
                            self.name, start, len(items), total, len(seen_ids))

                start += per_page
                if start >= total:
                    break
                if len(seen_ids) >= config.MAX_RESULTS_PER_QUERY:
                    logger.info("[%s] Reached result cap (%d) for query '%s'",
                                self.name, config.MAX_RESULTS_PER_QUERY, query)
                    break

        logger.info("[%s] Harvest complete. %d unique datasets found.", self.name, len(seen_ids))

    def _process_item(self, item: dict):
        global_id = item.get("global_id", "")
        name = item.get("name", "")
        url = item.get("url", "")
        description = item.get("description", "")
        published_at = item.get("published_at", "")

        # Extract authors from citation or contacts
        authors = []
        for contact in item.get("contacts", []):
            if isinstance(contact, dict):
                authors.append(contact.get("name", ""))
        # Also try authors field
        for author in item.get("authors", []):
            if isinstance(author, str):
                authors.append(author)

        # Store project metadata first (files will require a second API call)
        project_id = self.db.upsert_project(
            source_repository=self.repo_key,
            source_name=self.name,
            source_url=url,
            source_id=global_id,
            title=name,
            authors=authors if authors else [],
            description=description,
            license="",  # Will be filled from dataset detail if available
            doi=global_id.replace("doi:", "") if global_id.startswith("doi:") else "",
            publication_date=published_at,
            keywords=item.get("keywords", []),
            project_scope="",
            has_qda_files=0,
            metadata_json=item,
        )

        # Fetch detailed dataset info (includes files and license)
        self._fetch_dataset_details(project_id, global_id)

    def _fetch_dataset_details(self, project_id: int, persistent_id: str):
        """Fetch full dataset metadata including file list."""
        try:
            resp = self.get(
                f"{self.base_url}/api/datasets/:persistentId/",
                params={"persistentId": persistent_id},
            )
            if resp.status_code != 200:
                logger.debug("[%s] Dataset detail returned %d for %s",
                             self.name, resp.status_code, persistent_id)
                self.db.log_challenge(
                    "api_error",
                    f"Dataset detail HTTP {resp.status_code} for {persistent_id}",
                    project_id=project_id,
                    source_repository=self.repo_key,
                )
                return

            body = resp.json()
            data = body.get("data", body)
            latest = data.get("latestVersion", {})

            # Extract license
            license_name = latest.get("license", {}).get("name", "") if isinstance(
                latest.get("license"), dict
            ) else latest.get("license", "")
            terms = latest.get("termsOfUse", "")

            # Update license on the project
            if license_name:
                self.db.conn.execute(
                    "UPDATE projects SET license=?, updated_at=datetime('now') WHERE id=?",
                    (license_name, project_id),
                )
                self.db.conn.commit()

            # Extract files
            files_list = latest.get("files", [])
            for f_entry in files_list:
                df = f_entry.get("dataFile", f_entry)
                filename = df.get("filename", df.get("label", ""))
                file_id = df.get("id", "")
                size = df.get("filesize", df.get("originalFileSize"))
                checksum_val = df.get("md5", df.get("checksum", {}).get("value", ""))

                download_url = f"{self.base_url}/api/access/datafile/{file_id}" if file_id else ""
                ext = os.path.splitext(filename)[1].lower()
                file_type = classify_file(filename)

                self.db.insert_file(
                    project_id=project_id,
                    filename=filename,
                    file_extension=ext,
                    file_type=file_type,
                    file_size_bytes=size,
                    download_url=download_url,
                    checksum=checksum_val,
                )

            # Recompute QDA counts from files table
            self.db.update_qda_counts(project_id)

        except Exception as exc:
            logger.warning("[%s] Error fetching details for %s: %s",
                           self.name, persistent_id, exc)
            self.db.log_challenge(
                "api_error",
                f"Exception fetching dataset details for {persistent_id}: {exc}",
                project_id=project_id,
                source_repository=self.repo_key,
            )

    # ------------------------------------------------------------------
    # Download
    # ------------------------------------------------------------------
    def download_project_files(self, project_id: int):
        project = self.db.conn.execute(
            "SELECT * FROM projects WHERE id=?", (project_id,)
        ).fetchone()
        if not project:
            return

        dest_dir = os.path.join(
            config.DATA_DIR, self.repo_key,
            project["source_id"].replace(":", "_").replace("/", "_"),
        )
        os.makedirs(dest_dir, exist_ok=True)

        files = self.db.get_files_for_project(project_id)
        all_ok = True

        for f in files:
            if f["download_status"] == "downloaded":
                continue
            if not f["download_url"]:
                self.db.update_file_status(f["id"], "skipped")
                continue

            if f["file_size_bytes"] and f["file_size_bytes"] > config.MAX_FILE_SIZE_MB * 1024 * 1024:
                self.db.update_file_status(f["id"], "skipped")
                self.db.log_challenge(
                    "large_file",
                    f"File '{f['filename']}' exceeds size limit ({f['file_size_bytes']} bytes)",
                    project_id=project_id,
                    source_repository=self.repo_key,
                )
                continue

            local_path = os.path.join(dest_dir, f["filename"])
            try:
                self._download_file(f["download_url"], local_path)
                self.db.update_file_status(f["id"], "downloaded", local_path)
                logger.info("[%s] Downloaded: %s", self.name, f["filename"])
            except Exception as exc:
                all_ok = False
                self.db.update_file_status(f["id"], "failed")
                self.db.log_challenge(
                    "api_error",
                    f"Download failed for '{f['filename']}': {exc}",
                    project_id=project_id,
                    source_repository=self.repo_key,
                )

        self.db.update_project_status(project_id, "downloaded" if all_ok else "failed")

    def _download_file(self, url: str, dest: str):
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        resp = self.get(url, stream=True)
        resp.raise_for_status()
        with open(dest, "wb") as fh:
            for chunk in resp.iter_content(chunk_size=config.DOWNLOAD_CHUNK_SIZE):
                fh.write(chunk)
