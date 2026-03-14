# Seeding QDArchive

A Python pipeline for discovering and cataloging qualitative research data across open repositories. Built as part of the QDArchive project at FAU, where the long-term goal is to create an open archive for qualitative data analysis (QDA) files : think `.qdpx`, NVivo, MAXQDA, ATLAS.ti project files that researchers can actually reuse.

Right now, the pipeline focuses on harvesting metadata and file information from two assigned repositories:

- **Harvard Dataverse** (Dataset #10)
- **Columbia Oral History Archive** (Dataset #19)

> **Note:** This README will be updated as the project evolves across upcoming sessions and implementations.

---

## Motivation

There is a chicken-and-egg problem in qualitative research: no one shares QDA project files because there is no infrastructure for it, and no one builds the infrastructure because there aren't enough shared files to justify it. The REFI-QDA standard (`.qdpx`) exists to make QDA files interoperable between software like MAXQDA, NVivo, and ATLAS.ti but adoption is low because researchers don't have a place to publish or discover these files.

QDArchive is an attempt to break that cycle. Before building the archive itself, we need to understand what is already out there: which repositories host qualitative research data, what formats it's in, and whether any QDA project files exist in the wild.

That is what this pipeline does it systematically : searches repositories, collects metadata about every project and file it finds, classifies files by type (analysis, primary data, additional), and tracks everything in a local SQLite database.

---

## Project Structure

```
QDArchive-Project/
├── pipeline/
│   ├── __init__.py
│   ├── config.py               # Configuration — repos, queries, extensions, limits
│   ├── database.py             # SQLite schema, CRUD, QDA counts, CSV export
│   ├── orchestrator.py         # Coordinates harvesters and pipeline phases
│   └── harvesters/
│       ├── __init__.py
│       ├── base.py             # Abstract base class — HTTP session, rate limiting, retries
│       ├── dataverse.py        # Harvard Dataverse harvester (Dataverse Search API)
│       └── columbia.py         # Columbia DLC harvester (Blacklight JSON API)
├── run_pipeline.py             # CLI entry point — run the full pipeline
├── export_csv.py               # CLI — export database to per-repo and combined CSVs
├── requirements.txt            # Python dependencies (just requests)
├── .gitignore
├── qdarchive.db                # SQLite database (generated, gitignored)
├── data/                       # Downloaded files (gitignored)
│   ├── harvard_dataverse/
│   └── columbia_oral_history/
└── exports/                    # CSV exports 
    ├── harvard_dataverse/
    │   ├── projects.csv
    │   ├── files.csv
    │   └── technical_challenges.csv
    ├── columbia_oral_history/
    │   ├── projects.csv
    │   ├── files.csv
    │   └── technical_challenges.csv
    └── combined/
        ├── projects.csv
        ├── files.csv
        └── technical_challenges.csv
```

---

## How the Pipeline Works

The pipeline runs in three sequential phases:

### Phase 1 — Harvest

Searches each repository using 10 configured search queries (things like `"qdpx"`, `"qualitative data analysis"`, `"MAXQDA"`, `"interview transcript qualitative"`, etc.). For each result, it pulls project-level metadata (title, authors, DOI, description, license, keywords) and a file manifest (filenames, sizes, extensions, download URLs). Everything goes into the SQLite database using upsert logic, so re-running the pipeline updates existing records without creating duplicates.

**Harvard Dataverse:** Uses the standard Dataverse Search API (`/api/search`) in two phases:
- **Phase A (dataset search):** Searches with `type=dataset` to find datasets whose metadata matches the queries. For each result, a detail request to `/api/datasets/:persistentId/` fetches the file manifest.
- **Phase B (file search):** Searches with `type=file` to find files by name — including all 17 QDA extension patterns (e.g. `*.qdpx`, `*.nvp`, `*.atlproj`). This catches datasets that contain QDA files but don't mention QDA terms in their metadata. Parent datasets discovered this way are fetched and registered automatically.

For harvested datasets (indexed on Harvard but hosted elsewhere, e.g. Borealis, DANS, e-cienciaDatos), the detail API returns 401. In those cases, a fallback extracts file information from the search index itself.

**Columbia Oral History:** Uses the DLC Blacklight JSON API (`/catalog.json`), which was discovered empirically. Columbia's web interfaces are behind Anubis bot protection, but appending `.json` to catalog URLs returns structured data that works fine with `requests`. The harvester filters by `f[lib_repo_short_ssim][]=Oral History Center` and runs a two-phase approach: a broad sweep of the collection plus targeted keyword queries.

### Phase 2 — Download

Iterates over projects with `download_status='pending'` and downloads their files into `data/<repo>/<project_id>/`. Respects a configurable file size limit (default 500 MB) and skips files that are too large. Tracks download success/failure per file in the database.

Columbia content is streaming-only — the DLC API doesn't expose direct download URLs, so Columbia files get marked as `skipped` during this phase. Harvard Dataverse files download normally via `/api/access/datafile/<fileId>`.

### Phase 3 — Export

Exports the database to CSV files, separated by repository. Each repo gets its own directory under `exports/` with `projects.csv`, `files.csv`, and `technical_challenges.csv`. A `combined/` directory merges everything.

---

## Code Architecture

```
                  run_pipeline.py / export_csv.py
                           │
                    orchestrator.py
                    (factory + 3 phases)
                     ╱            ╲
          DataverseHarvester    ColumbiaHarvester
                     ╲            ╱
                   BaseHarvester (ABC)
                   (HTTP session, rate limiting,
                    retries, file classification)
                           │
                      database.py
                   (SQLite, upsert, export)
                           │
                      config.py
                   (queries, repos, extensions)
```

- **BaseHarvester** — Abstract base class. Manages an HTTP session with a custom User-Agent, rate limiting between requests, and retry logic with exponential backoff (handles 429 Too Many Requests with Retry-After). Also has `classify_file()` which categorizes files as `analysis` (QDA extensions), `primary` (common data formats), or `additional` based on their extension.

- **DataverseHarvester** — Implements harvesting for any Dataverse installation. Two-phase search: dataset-level search for metadata matches + file-level search for QDA file patterns. Includes a fallback for harvested datasets whose detail API returns 401. Updates QDA file counts per project after registering files.

- **ColumbiaHarvester** — Custom harvester for Columbia's Digital Library Collections platform. Parses Fedora repository metadata, registers child resources (audio, video, text) as files with guessed extensions based on format type. Marks downloads as skipped since DLC doesn't provide direct file access.

- **Database** — SQLite with WAL mode and foreign key enforcement. Three tables: `projects` (24 columns), `files` (12 columns), `technical_challenges` (6 columns). Supports upsert on `(source_repository, source_id)` to prevent duplicates. Has methods for QDA count computation, per-repo filtering, and CSV export.

- **Orchestrator** — Factory pattern for creating harvesters based on repository type. Coordinates the three pipeline phases and produces a summary dict.

---

## Getting Started

### Prerequisites

- Python 3.10+ (developed on 3.13)
- `pip`

### Installation

```bash
git clone https://github.com/annus3/QDArchive-Project.git
cd QDArchive-Project
pip install -r requirements.txt
```

The only external dependency is `requests`.

### Running the Pipeline

```bash
# Full pipeline — harvest metadata + download files + export CSVs
python run_pipeline.py

# Harvest only (collect metadata, skip downloads)
python run_pipeline.py --harvest-only

# Specific repositories
python run_pipeline.py --repos harvard_dataverse
python run_pipeline.py --repos columbia_oral_history

# Custom search queries (overrides the 10 default queries)
python run_pipeline.py --queries "qdpx" "NVivo qualitative" "interview transcript"

# Only download projects that contain QDA files
python run_pipeline.py --qda-only

# Verbose logging
python run_pipeline.py --log-level DEBUG
```

### Exporting to CSV

```bash
# Export per-repo + combined CSVs
python export_csv.py

# Export only one repository
python export_csv.py --repo harvard_dataverse

# Custom output directory
python export_csv.py --output ./my_exports
```

---

## Configuration

All settings live in `pipeline/config.py`:

| Setting | Default | What it controls |
|---------|---------|------------------|
| `SEARCH_QUERIES` | 10 queries | Search terms sent to each repository API |
| `MAX_RESULTS_PER_QUERY` | 250 | Cap on results per query to prevent runaway pagination |
| `MAX_FILE_SIZE_MB` | 500 | Files larger than this are skipped |
| `DOWNLOAD_TIMEOUT_SECONDS` | 300 | Per-file download timeout |
| `MAX_RETRIES` | 3 | Retry attempts for failed HTTP requests |
| `QDA_EXTENSIONS` | 17 types | File extensions recognized as QDA analysis files |
| `PRIMARY_DATA_EXTENSIONS` | ~30 types | Extensions classified as primary research data |
| `REPOSITORIES` | 2 repos | Repository definitions (URL, type, rate limit) |

The 10 default search queries: `qdpx`, `qualitative data analysis`, `qualitative research data`, `MAXQDA`, `NVivo qualitative`, `ATLAS.ti qualitative`, `interview transcript qualitative`, `thematic analysis data`, `grounded theory data`, `codebook qualitative`.

QDA extensions currently recognized: `.qdpx`, `.mx24`, `.mx22`, `.mx20`, `.mx18`, `.mx12`, `.mex`, `.nvp`, `.nvpx`, `.hpr`, `.atlproj`, `.qda`, `.cat`, `.hermeneutic`, `.hnsp`, `.kdp`, `.qde`.

---

## Database Schema

Three tables in `qdarchive.db` (SQLite):

**projects** — One row per discovered dataset/collection. Key columns: `source_repository`, `source_id`, `title`, `authors` (JSON), `description`, `doi`, `license`, `keywords` (JSON), `has_qda_files`, `qda_file_count`, `qdpx_file_count`, `maxqda_file_count`, `download_status`, `metadata_json` (raw API response). Unique constraint on `(source_repository, source_id)`.

**files** — One row per file within a project. Columns: `project_id` (FK), `filename`, `file_extension`, `file_type` (analysis/primary/additional/unknown), `file_size_bytes`, `download_url`, `checksum`, `download_status`.

**technical_challenges** — Logs data-related issues encountered during harvesting: `challenge_type` (rate_limit, access_denied, api_error, etc.), `description`, linked to project and repository.

---

## Harvest Results

Results from the most recent harvest run:

| Repository | Projects | Files | With DOI | With Description | With License | QDA Files |
|-----------|----------|-------|----------|-----------------|-------------|-----------|
| Harvard Dataverse | 632 | 15,213 | 632 | 631 | 515 | 36 |
| Columbia Oral History | 626 | 1,392 | 626 | 444 | 107 | 0 |
| **Total** | **1,258** | **16,605** | **1,258** | **1,075** | **622** | **36** |

### QDA Files Found

The pipeline discovered **36 QDA analysis files** across **27 projects** on Harvard Dataverse:

| Format | Count | Software |
|--------|-------|----------|
| `.qdpx` | 27 | REFI-QDA standard (interoperable) |
| `.nvp` | 5 | NVivo (older format) |
| `.nvpx` | 3 | NVivo (newer format) |
| `.atlproj` | 1 | ATLAS.ti |

These files were discovered through the file-level search (`type=file`) which searches by filename and file description — catching datasets that contain QDA files even when their metadata text doesn't mention QDA terms. Most of the hosting datasets are from external Dataverse installations (DANS, Borealis, QDR, e-cienciaDatos) that are indexed in Harvard's federated search.

Columbia's Oral History Archive contains qualitative *primary data* (audio/video recordings of oral history interviews) but no QDA analysis project files.

---

## Reproducibility

The pipeline is idempotent. Running it again will:
- Update existing projects via upsert (matched by `source_repository` + `source_id`)
- Skip already-downloaded files
- Pick up any new datasets added since the last run

To reproduce from scratch:
```bash
# Delete the database and re-harvest
rm qdarchive.db
python run_pipeline.py --harvest-only
python export_csv.py
```

The database and downloaded files are gitignored. CSV exports under `exports/` contain the harvested data.

---

## Known Limitations

- **Columbia downloads not available** — The DLC platform doesn't expose direct download URLs in its public API. Content is streaming-only or requires institutional access. The harvester catalogs everything it finds but can't download the actual files.

- **QDA files are rare** — Out of 1,258 projects and 16,605 files, only 36 QDA analysis files were found (27 `.qdpx`, 5 `.nvp`, 3 `.nvpx`, 1 `.atlproj`). All from Harvard Dataverse; Columbia Oral History has none. This confirms the hypothesis that QDA project files are rarely shared, which is the gap QDArchive is meant to fill.

- **Some Harvard datasets return 401** — A few datasets on Harvard Dataverse are `*_harvested` entries (from Borealis, e-cienciaDatos, etc.) that return HTTP 401 when fetching file details. These are logged as technical challenges but don't block the pipeline.

- **Columbia bot protection** — Columbia's web interfaces use Anubis challenge pages. The JSON API bypasses this, but it is an undocumented endpoint that could change.

- **No cross-repository deduplication** — The same dataset could theoretically appear on multiple repositories. Dedup by DOI is a planned enhancement.

- **Classification is Part 2** — File classification into qualitative research categories hasn't started yet. The current `file_type` field uses a simple extension-based approach (analysis vs. primary vs. additional).

---

## Future Work

- **Part 2 — Classification:** Categorize harvested datasets by qualitative research methodology, data type, and reuse potential.
- **Part 3 — Analysis:** Analyze the landscape of qualitative research data across repositories.
- **Cross-repository deduplication** by DOI.
- **Additional repositories** — The broader QDArchive project identified 20+ repositories; only 2 are assigned to this pipeline so far.
- **Richer file classification** beyond extension-based heuristics.

---

*Part of the Seeding QDArchive project at FAU Erlangen-Nürnberg.*
