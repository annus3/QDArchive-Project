"""
Columbia Oral History Archive harvester.

Uses the DLC (Digital Library Collections) Blacklight JSON API at
  https://dlc.library.columbia.edu/catalog.json

The Oral History Center's items are retrieved via the facet:
  f[lib_repo_short_ssim][]=Oral History Center

Each top-level item is a Fedora ContentAggregator whose children
(GenericResource) contain the actual media files (audio, video, text).

API docs are not published — endpoints were discovered empirically.
"""

import json
import logging
import os

from .. import config
from ..database import Database
from .base import BaseHarvester, classify_file

logger = logging.getLogger(__name__)


class ColumbiaHarvester(BaseHarvester):
    """Harvest oral history items from Columbia's DLC platform."""

    FACET_KEY = "f[lib_repo_short_ssim][]"
    FACET_VALUE = "Oral History Center"
    SEARCH_FIELD = "all_text_teim"

    def __init__(self, db: Database, repo_key: str = "columbia_oral_history"):
        super().__init__(repo_key, db)

    # ------------------------------------------------------------------
    # Harvest
    # ------------------------------------------------------------------
    def harvest(self, queries: list[str] | None = None):
        """
        Harvest items from the Columbia Oral History Center.

        Because the DLC search within the OHC facet is full-text, we first
        do a broad sweep (no query) to get everything, then optionally
        refine with keyword queries.
        """
        seen_ids: set[str] = set()

        # Phase A: Broad collection sweep (all items under OHC)
        logger.info("[%s] Broad sweep of Oral History Center collection …", self.name)
        self._paginate_search(params={}, seen_ids=seen_ids,
                              max_results=config.MAX_RESULTS_PER_QUERY)

        # Phase B: Keyword queries for qualitative-research-relevant items
        queries = queries or config.SEARCH_QUERIES
        for query in queries:
            logger.info("[%s] Keyword search: %s", self.name, query)
            self._paginate_search(
                params={"q": query, "search_field": self.SEARCH_FIELD},
                seen_ids=seen_ids,
                max_results=config.MAX_RESULTS_PER_QUERY,
            )

        logger.info("[%s] Harvest complete. %d unique items cataloged.",
                     self.name, len(seen_ids))

    def _paginate_search(self, params: dict, seen_ids: set[str],
                         max_results: int):
        """Paginate through the DLC catalog JSON endpoint."""
        page = 1
        per_page = 100

        base_params = {
            self.FACET_KEY: self.FACET_VALUE,
            "per_page": per_page,
        }
        base_params.update(params)

        while True:
            base_params["page"] = page
            resp = self.get(f"{self.base_url}/catalog.json", params=base_params)

            if resp.status_code != 200:
                logger.warning("[%s] Search returned %d (page %d)",
                               self.name, resp.status_code, page)
                self.db.log_challenge(
                    "api_error",
                    f"DLC catalog returned HTTP {resp.status_code} on page {page}",
                    source_repository=self.repo_key,
                )
                break

            body = resp.json()
            meta = body.get("meta", {}).get("pages", {})
            total = meta.get("total_count", 0)
            items = body.get("data", [])

            if not items:
                break

            for item in items:
                item_id = item.get("id", "")
                if not item_id or item_id in seen_ids:
                    continue
                seen_ids.add(item_id)
                self._process_list_item(item)

            logger.info("[%s] Page %d — %d items (total available: %d, collected: %d)",
                        self.name, page, len(items), total, len(seen_ids))

            if page >= meta.get("total_pages", 1):
                break
            if len(seen_ids) >= max_results:
                logger.info("[%s] Reached result cap (%d)", self.name, max_results)
                break

            page += 1

    # ------------------------------------------------------------------
    # Item processing
    # ------------------------------------------------------------------
    def _process_list_item(self, item: dict):
        """Process a single item from the DLC list API response."""
        item_id = item["id"]
        attrs = item.get("attributes", {})

        title = attrs.get("title", "")

        # Extract nested attribute values
        def _attr_val(key):
            obj = attrs.get(key)
            if isinstance(obj, dict):
                return obj.get("attributes", {}).get("value", "")
            return ""

        collection = _attr_val("lib_collection_ssm")
        primary_name = _attr_val("primary_name_ssm")
        date_text = _attr_val("lib_date_textual_ssm")

        authors = [primary_name] if primary_name else []
        if isinstance(collection, list):
            collection = "; ".join(collection)
        if isinstance(authors[0] if authors else "", list):
            authors = authors[0]

        # Construct URL
        source_url = item.get("links", {}).get("self", "")
        if not source_url:
            source_url = f"{self.base_url}/catalog/{item_id}"

        # Store basic metadata (detail fetch will enrich)
        project_id = self.db.upsert_project(
            source_repository=self.repo_key,
            source_name=self.name,
            source_url=source_url,
            source_id=item_id,
            title=title,
            authors=authors,
            description="",
            license="",
            doi="",
            publication_date=str(date_text) if date_text else "",
            keywords=[],
            project_scope=str(collection) if collection else "Oral History",
            has_qda_files=0,
            metadata_json={"list_item": item},
        )

        # Fetch detailed metadata
        self._fetch_detail(project_id, item_id)

    def _fetch_detail(self, project_id: int, item_id: str):
        """Fetch full item metadata from the detail endpoint."""
        try:
            resp = self.get(f"{self.base_url}/catalog/{item_id}.json")
            if resp.status_code != 200:
                logger.debug("[%s] Detail returned %d for %s",
                             self.name, resp.status_code, item_id)
                self.db.log_challenge(
                    "api_error",
                    f"Detail HTTP {resp.status_code} for {item_id}",
                    project_id=project_id,
                    source_repository=self.repo_key,
                )
                return

            body = resp.json()
            doc = body.get("response", {}).get("document", {})
            if not doc:
                return

            # Extract DOI
            dois = doc.get("ezid_doi_ssim", [])
            doi = dois[0].replace("doi:", "") if dois else ""

            # Abstract
            abstracts = doc.get("abstract_ssm", [])
            description = abstracts[0] if abstracts else ""

            # Subjects
            subjects = doc.get("lib_all_subjects_ssm", [])

            # Authors / names
            names = doc.get("lib_name_ssm", [])
            primary = doc.get("primary_name_ssm", [])
            authors = primary if primary else names

            # Collection
            collection = doc.get("lib_collection_ssm", [])
            if isinstance(collection, list):
                collection = "; ".join(collection)

            # License / rights
            copyright_stmt = doc.get("copyright_statement_ssi", "")
            restriction_on_access = doc.get("restriction_on_access_ssm", [])
            license_info = copyright_stmt
            if restriction_on_access:
                license_info += f" | Access: {'; '.join(restriction_on_access)}"

            # Dates
            date_created = doc.get("origin_info_date_created_ssm", [])
            pub_date = date_created[0] if date_created else ""

            # Format / type
            formats = doc.get("lib_format_ssm", [])
            resource_type = doc.get("type_of_resource_ssm", [])

            # Number of child resources (media files)
            num_members = doc.get("cul_number_of_members_isi", 0)

            # URL for digital content
            location_urls = []
            loc_json_str = doc.get("location_url_json_ss", "[]")
            try:
                loc_data = json.loads(loc_json_str) if isinstance(loc_json_str, str) else loc_json_str
                if isinstance(loc_data, list):
                    for entry in loc_data:
                        if isinstance(entry, dict) and entry.get("url"):
                            location_urls.append(entry["url"])
            except (json.JSONDecodeError, TypeError):
                pass

            # Update project with enriched data
            self.db.upsert_project(
                source_repository=self.repo_key,
                source_name=self.name,
                source_url=f"{self.base_url}/catalog/{item_id}",
                source_id=item_id,
                title=doc.get("dc_title_ssm", [""])[0] if doc.get("dc_title_ssm") else "",
                authors=authors,
                description=description,
                license=license_info,
                doi=doi,
                publication_date=pub_date,
                keywords=subjects,
                project_scope=collection if collection else "Oral History",
                has_qda_files=0,
                metadata_json=doc,
            )

            # Register child resources as files (skip if already registered)
            existing_files = self.db.get_files_for_project(project_id)
            if num_members and num_members > 0 and not existing_files:
                self._register_child_resources(project_id, item_id, doc, num_members,
                                               formats, resource_type, location_urls)

            # Recompute QDA counts from files table
            self.db.update_qda_counts(project_id)

        except Exception as exc:
            logger.warning("[%s] Error fetching detail for %s: %s",
                           self.name, item_id, exc)
            self.db.log_challenge(
                "api_error",
                f"Exception fetching detail for {item_id}: {exc}",
                project_id=project_id,
                source_repository=self.repo_key,
            )

    def _register_child_resources(self, project_id: int, parent_id: str,
                                  doc: dict, num_members: int,
                                  formats: list, resource_types: list,
                                  location_urls: list):
        """Register child media resources as file entries."""
        # The DLC doesn't expose direct download URLs for content datastreams
        # in the public API. We register a reference entry for each known child.
        # For items with DOIs, the DOI landing page provides access.

        representative_pid = doc.get("representative_generic_resource_pid_ssi", "")

        # Register summary file entries based on known format info
        for i, fmt in enumerate(formats):
            ext_map = {
                "oral histories": ".txt",
                "sound recordings": ".mp3",
                "video recordings": ".mp4",
                "text": ".pdf",
                "moving images": ".mp4",
                "still images": ".jpg",
            }
            guessed_ext = ""
            for key, ext in ext_map.items():
                if key in fmt.lower():
                    guessed_ext = ext
                    break

            filename = f"{parent_id.replace(':', '_')}_{fmt.replace(' ', '_')}{guessed_ext}"
            file_type = classify_file(filename)

            # Content URL (if derivable)
            download_url = ""
            if representative_pid and i == 0:
                download_url = f"{self.base_url}/catalog/{representative_pid}"

            self.db.insert_file(
                project_id=project_id,
                filename=filename,
                file_extension=guessed_ext,
                file_type=file_type,
                file_size_bytes=None,
                download_url=download_url,
                checksum="",
            )

        # Also register DOI landing page links as reference files
        for url in location_urls:
            self.db.insert_file(
                project_id=project_id,
                filename=f"{parent_id.replace(':', '_')}_doi_landing",
                file_extension=".url",
                file_type="additional",
                file_size_bytes=None,
                download_url=url,
                checksum="",
            )

    # ------------------------------------------------------------------
    # Download
    # ------------------------------------------------------------------
    def download_project_files(self, project_id: int):
        """
        Columbia DLC does not expose direct download URLs for content
        datastreams in the public API — media access requires authentication
        or is streaming-only. We mark files as 'skipped' and log the challenge.
        """
        project = self.db.conn.execute(
            "SELECT * FROM projects WHERE id=?", (project_id,)
        ).fetchone()
        if not project:
            return

        files = self.db.get_files_for_project(project_id)
        for f in files:
            if f["download_status"] == "downloaded":
                continue
            # DLC content is not directly downloadable via public API
            self.db.update_file_status(f["id"], "skipped")

        self.db.update_project_status(project_id, "skipped")
        self.db.log_challenge(
            "access_denied",
            f"Columbia DLC does not expose direct download URLs. "
            f"Access via DOI: {project['doi'] or 'N/A'}",
            project_id=project_id,
            source_repository=self.repo_key,
        )
