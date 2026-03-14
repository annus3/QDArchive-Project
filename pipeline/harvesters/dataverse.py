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

        # --- Phase A: dataset-level search --------------------------------
        for query in queries:
            logger.info("[%s] Dataset search: %s", self.name, query)
            self._search_datasets(query, seen_ids)

        # --- Phase B: file-level search -----------------------------------
        # The dataset search only finds datasets whose *metadata text*
        # matches the query.  Datasets that *contain* matching files (e.g.
        # a .qdpx file) but don't mention the term in their title or
        # description are missed.  The Dataverse Search API supports
        # type=file which searches file names/descriptions directly and
        # returns the parent dataset_persistent_id for each hit.
        file_queries = self._build_file_queries(queries)
        for query in file_queries:
            logger.info("[%s] File search: %s", self.name, query)
            self._search_files(query, seen_ids)

        logger.info("[%s] Harvest complete. %d unique datasets found.", self.name, len(seen_ids))

    # ------------------------------------------------------------------
    # Search helpers
    # ------------------------------------------------------------------
    def _search_datasets(self, query: str, seen_ids: set[str]):
        """Run a type=dataset search and process results."""
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

    @staticmethod
    def _build_file_queries(queries: list[str]) -> list[str]:
        """Build a deduplicated list of file-level queries.

        Includes the original queries plus explicit QDA extension patterns
        (e.g. ``*.qdpx``) so that we discover files by name even when the
        dataset metadata doesn't mention QDA terms.
        """
        fq: list[str] = list(queries)
        for ext in sorted(config.QDA_EXTENSIONS):
            pattern = f"*{ext}"
            if pattern not in fq:
                fq.append(pattern)
        return fq

    def _search_files(self, query: str, seen_ids: set[str]):
        """Run a type=file search, discover parent datasets, and process them."""
        start = 0
        per_page = 100

        while True:
            resp = self.get(
                f"{self.base_url}/api/search",
                params={
                    "q": query,
                    "type": "file",
                    "start": start,
                    "per_page": per_page,
                },
            )
            if resp.status_code != 200:
                logger.warning("[%s] File search returned %d for '%s'",
                               self.name, resp.status_code, query)
                break

            body = resp.json()
            data = body.get("data", body)
            items = data.get("items", [])
            total = data.get("total_count", 0)

            if not items:
                break

            for item in items:
                dataset_id = item.get("dataset_persistent_id", "")
                if not dataset_id:
                    continue

                filename = item.get("name", "")
                if not filename:
                    continue

                if dataset_id not in seen_ids:
                    # Brand-new dataset discovered via file search
                    seen_ids.add(dataset_id)
                    logger.info("[%s] File search found new dataset: %s (via file '%s')",
                                self.name, dataset_id, filename)
                    self._process_item_from_file_hit(dataset_id, item)
                else:
                    # Dataset already known — register the file if not already present
                    self._register_file_from_search(dataset_id, item)

            start += per_page
            if start >= total:
                break

    def _process_item_from_file_hit(self, dataset_id: str, file_item: dict):
        """Create/upsert a project from a file-level search hit, then fetch details."""
        dataset_name = file_item.get("dataset_name", "")
        dataset_citation = file_item.get("dataset_citation", "")
        url = file_item.get("url", "")
        # The file URL looks like .../dataset.xhtml?persistentId=...&... — derive dataset URL
        doi = dataset_id.replace("doi:", "") if dataset_id.startswith("doi:") else ""
        dataset_url = f"https://doi.org/{doi}" if doi else url

        project_id = self.db.upsert_project(
            source_repository=self.repo_key,
            source_name=self.name,
            source_url=dataset_url,
            source_id=dataset_id,
            title=dataset_name,
            authors=[],
            description=dataset_citation,
            license="",
            doi=doi,
            publication_date="",
            keywords=[],
            project_scope="",
            has_qda_files=0,
            metadata_json=file_item,
        )

        self._fetch_dataset_details(project_id, dataset_id)

    def _register_file_from_search(self, dataset_id: str, file_item: dict):
        """Register a single file from a file-level search hit into an existing project."""
        row = self.db.conn.execute(
            "SELECT id FROM projects WHERE source_repository=? AND source_id=?",
            (self.repo_key, dataset_id),
        ).fetchone()
        if not row:
            return
        project_id = row["id"]

        filename = file_item.get("name", "")
        if not filename:
            return
        ext = os.path.splitext(filename)[1].lower()
        file_type = classify_file(filename)
        size = file_item.get("size_in_bytes") if file_item.get("size_in_bytes", -1) > 0 else None
        file_id = file_item.get("file_id", "")
        checksum_info = file_item.get("checksum")
        checksum_val = checksum_info.get("value", "") if isinstance(checksum_info, dict) else ""
        download_url = f"{self.base_url}/api/access/datafile/{file_id}" if file_id else ""

        self.db.insert_file(
            project_id=project_id,
            filename=filename,
            file_extension=ext,
            file_type=file_type,
            file_size_bytes=size,
            download_url=download_url,
            checksum=checksum_val,
        )
        self.db.update_qda_counts(project_id)

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
        """Fetch full dataset metadata including file list.

        If the detail API returns a non-200 (e.g. 401 for harvested
        datasets), falls back to a file-level search to discover files
        belonging to this dataset.
        """
        try:
            resp = self.get(
                f"{self.base_url}/api/datasets/:persistentId/",
                params={"persistentId": persistent_id},
            )
            if resp.status_code != 200:
                logger.debug("[%s] Dataset detail returned %d for %s — trying file search fallback",
                             self.name, resp.status_code, persistent_id)
                self.db.log_challenge(
                    "api_error",
                    f"Dataset detail HTTP {resp.status_code} for {persistent_id}",
                    project_id=project_id,
                    source_repository=self.repo_key,
                )
                self._fallback_file_search(project_id, persistent_id)
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

    def _fallback_file_search(self, project_id: int, persistent_id: str):
        """Discover files for a dataset via the file-level search API.

        Used when the dataset detail endpoint returns 401/403 (common
        for harvested datasets).  Tries multiple search strategies to
        find file entries whose ``dataset_persistent_id`` matches.
        """
        # Build candidate queries — DOI parts, dataset ID, etc.
        doi = persistent_id.replace("doi:", "") if persistent_id.startswith("doi:") else persistent_id
        # Try the last path segment of the DOI (most distinctive part)
        doi_suffix = doi.rsplit("/", 1)[-1] if "/" in doi else doi
        search_terms = [f'"{doi}"', f'"{doi_suffix}"']
        # Deduplicate
        search_terms = list(dict.fromkeys(search_terms))

        try:
            registered = 0
            for term in search_terms:
                resp = self.get(
                    f"{self.base_url}/api/search",
                    params={"q": term, "type": "file", "per_page": 100},
                )
                if resp.status_code != 200:
                    continue

                body = resp.json()
                items = body.get("data", body).get("items", [])
                for item in items:
                    if item.get("dataset_persistent_id") != persistent_id:
                        continue
                    filename = item.get("name", "")
                    if not filename:
                        continue
                    ext = os.path.splitext(filename)[1].lower()
                    file_type = classify_file(filename)
                    size = item.get("size_in_bytes") if item.get("size_in_bytes", -1) > 0 else None
                    file_id = item.get("file_id", item.get("entity_id", ""))
                    checksum_info = item.get("checksum")
                    checksum_val = checksum_info.get("value", "") if isinstance(checksum_info, dict) else ""
                    download_url = f"{self.base_url}/api/access/datafile/{file_id}" if file_id else ""

                    self.db.insert_file(
                        project_id=project_id,
                        filename=filename,
                        file_extension=ext,
                        file_type=file_type,
                        file_size_bytes=size,
                        download_url=download_url,
                        checksum=checksum_val,
                    )
                    registered += 1

                if registered:
                    break  # Found files, no need to try other search terms

            if registered:
                logger.info("[%s] Fallback file search registered %d files for %s",
                            self.name, registered, persistent_id)
            self.db.update_qda_counts(project_id)

        except Exception as exc:
            logger.warning("[%s] Fallback file search failed for %s: %s",
                           self.name, persistent_id, exc)

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
