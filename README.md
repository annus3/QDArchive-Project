# Seeding QDArchive

A Python pipeline for discovering and cataloging qualitative research data across open repositories. Built as part of the QDArchive project at FAU, where the long-term goal is to create an open archive for qualitative data analysis (QDA) files : think `.qdpx`, NVivo, MAXQDA, ATLAS.ti project files that researchers can actually reuse.

Right now, the pipeline focuses on harvesting metadata and file information from two assigned repositories:

| # | Dataset | URL |
|---|---------|-----|
| 10 | Harvard Dataverse | [dataverse.harvard.edu](https://dataverse.harvard.edu/) |
| 19 | Columbia Oral History Archive | [dlc.library.columbia.edu](https://dlc.library.columbia.edu/) |

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
│   ├── harvesters/
│   │   ├── __init__.py
│   │   ├── base.py             # Abstract base class — HTTP session, rate limiting, retries
│   │   ├── columbia.py         # Columbia DLC harvester (Blacklight JSON API)
│   │   └── dataverse.py        # Harvard Dataverse harvester (Dataverse Search API)
│   ├── __init__.py
│   ├── config.py               # Configuration — repos, queries, extensions, limits
│   ├── database.py             # SQLite schema, CRUD, QDA counts, CSV export
│   ├── orchestrator.py         # Coordinates harvesters and pipeline phases
│   └── progress.py             # Harvest progress/resume state tracker
├── data/                         # Downloaded files (gitignored)
│   ├── harvard_dataverse/
│   │   └── doi_10.xxxx_xxx/      # QDA + primary + additional files
│   └── columbia_oral_history/
│       └── cul_xxx/
│           └── metadata.json     # Full API metadata (media is auth-gated)
├── exports/                      # CSV exports (gitignored)
│   ├── harvard_dataverse/
│   │   ├── projects.csv
│   │   ├── files.csv
│   │   └── ...
│   ├── columbia_oral_history/
│   │   ├── projects.csv
│   │   ├── files.csv
│   │   └── ...
│   └── combined/
│       └── ...
├── .gitignore
├── 23221189-sq26.db            # SQLite database (generated)
├── LICENSE
├── README.md
├── export_csv.py               # CLI — export database to per-repo and combined CSVs
├── requirements.txt            # Python dependencies (just requests)
└── run_pipeline.py             # CLI entry point — run the full pipeline
```

---

## How the Pipeline Works

The pipeline runs in three sequential phases:

### Phase 1 — Harvest

Searches each repository using 25 configured search queries (13 CAQDAS tool names + 12 methodology keywords) — tool-specific terms like `"qdpx"`, `"MAXQDA"`, `"NVivo"`, `"ATLAS.ti"` plus quoted methodology phrases like `"qualitative data analysis"`, `"thematic analysis"`, `"grounded theory"`. For each result, it pulls project-level metadata (title, authors, DOI, description, license, keywords) and a file manifest (filenames, sizes, extensions, download URLs). Everything goes into the SQLite database using upsert logic, so re-running the pipeline updates existing records without creating duplicates.

**Harvard Dataverse:** Uses the standard Dataverse Search API (`/api/search`) in two phases:
- **Phase A (dataset search):** Searches with `type=dataset` to find datasets whose metadata matches the queries. For each result, a detail request to `/api/datasets/:persistentId/` fetches the file manifest.
- **Phase B (file search):** Searches with `type=file` to find files by name — including all 42 QDA extension patterns (e.g. `*.qdpx`, `*.nvp`, `*.atlproj`). This catches datasets that contain QDA files but don't mention QDA terms in their metadata. Parent datasets discovered this way are fetched and registered automatically.

For harvested datasets (indexed on Harvard but hosted elsewhere, e.g. Borealis, DANS, e-cienciaDatos), the detail API returns 401. In those cases, a fallback extracts file information from the search index itself.

**Columbia Oral History:** Uses the DLC Blacklight JSON API (`/catalog.json`), which was discovered empirically. Columbia's web interfaces are behind Anubis bot protection, but appending `.json` to catalog URLs returns structured data that works fine with `requests`. The harvester filters by `f[lib_repo_short_ssim][]=Oral History Center` and runs a two-phase approach: a broad sweep of the collection plus targeted keyword queries.

### Phase 2 — Download

Uses a **two-pass strategy** with a shared global byte budget (default 6 GB):

- **Pass 1 (QDA-first):** Downloads only analysis files (QDA extensions) across all repos. Retries previously failed downloads. For Columbia, saves full JSON metadata per project.
- **Pass 2 (remaining):** Downloads primary and additional data files from Harvard Dataverse projects until the budget is exhausted.

If `--qda-only` is passed, Pass 2 is skipped entirely.

Harvard Dataverse files download via `/api/access/datafile/<fileId>`. Columbia content is streaming-only — the harvester saves the full API metadata JSON as `metadata.json` in each project’s directory.

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

- **ColumbiaHarvester** — Custom harvester for Columbia's Digital Library Collections platform. Parses Fedora repository metadata, registers child resources (audio, video, text) as files with guessed extensions based on format type. Downloads full JSON metadata per project since DLC media is auth-gated and not directly accessible.

- **Database** — SQLite with WAL mode and foreign key enforcement. Six tables: `projects` (30+ columns), `files` (13 columns), `keywords`, `person_role`, `licenses`, and `technical_challenges`. Supports upsert on `(source_repository, source_id)` to prevent duplicates. Has methods for QDA count computation, per-repo filtering, and CSV export.

- **Orchestrator** — Factory pattern for creating harvesters based on repository type. Coordinates the three pipeline phases. Downloads use a two-pass strategy: Pass 1 fetches QDA (analysis) files first, Pass 2 fetches remaining files. Both share a global byte budget (`MAX_TOTAL_DOWNLOAD_GB`).

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

# Custom search queries (overrides the 25 default queries)
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
| `SEARCH_QUERIES` | 25 queries | Combined Tier 2 (13 tool names) + Tier 3 (12 methodology keywords) |
| `MAX_RESULTS_PER_QUERY` | 250 | Cap on results per query to prevent runaway pagination |
| `MAX_FILE_SIZE_MB` | 0 (no limit) | Files larger than this (MB) are skipped; 0 = download all |
| `MAX_TOTAL_DOWNLOAD_GB` | 6 | Global download budget in GB; 0 = unlimited |
| `DOWNLOAD_TIMEOUT_SECONDS` | 600 | Per-file download timeout (10 minutes) |
| `MAX_RETRIES` | 3 | Retry attempts for failed HTTP requests |
| `QDA_EXTENSIONS` | 42 types | File extensions recognized as QDA analysis files |
| `PRIMARY_DATA_EXTENSIONS` | ~30 types | Extensions classified as primary research data |
| `REPOSITORIES` | 2 repos | Repository definitions (URL, type, rate limit) |
| `BATCH_COMMIT_SIZE` | 50 | Commit to DB every N operations (batch writes) |
| `PROGRESS_FILE` | `qdarchive.progress.json` | Path to harvest progress/resume state file |

The 25 search queries are organized into a **3-tier system** defined in `pipeline/config.py`:

- **Tier 1** (42 extension patterns): Handled by file-level search in the Dataverse harvester (`*.qdpx`, `*.nvp`, etc.)
- **Tier 2** (13 tool queries): `qdpx`, `REFI-QDA`, `MAXQDA`, `NVivo`, `ATLAS.ti`, `QDA Miner`, `QDAcity`, `f4analyse`, `Dedoose`, `Quirkos`, `HyperRESEARCH`, `Kwalitan`, `CAQDAS`
- **Tier 3** (12 methodology queries): `"qualitative data analysis"`, `"thematic analysis"`, `"grounded theory"`, `"qualitative coding"`, and more

QDA extensions are recognized from 9 tools (42 extensions total):
- **REFI-QDA:** `.qdpx`
- **MAXQDA:** `.mqda`, `.mqbac`, `.mqtc`, `.mqex`, `.mqmtr`, `.mx24`, `.mx24bac`, `.mc24`, `.mex24`, `.mx22`, `.mex22`, `.mx20`, `.mx18`, `.mx12`, `.mx11`, `.mx5`, `.mx4`, `.mx3`, `.mx2`, `.m2k`, `.mtr`, `.loa`, `.sea`
- **NVivo:** `.nvp`, `.nvpx`
- **ATLAS.ti:** `.atlasproj`, `.atlproj`, `.hpr`, `.hpr7`, `.hermeneutic`
- **QDAcity:** `.qdc`
- **QDA Miner:** `.qda`, `.ppj`, `.pprj`, `.qlt`
- **f4analyse:** `.f4p`
- **Quirkos:** `.qpd`, `.qde`
- **Other:** `.cat` (Coding Analysis Toolkit), `.hnsp` (HyperRESEARCH), `.kdp` (Kwalitan)

> **Note:** Generic `.mex` and `.mod` extensions were removed after investigation — `.mex` files on Dataverse are overwhelmingly MATLAB MEX compiled binaries, and `.mod` files are Dynare/GAMS economic model scripts. The version-specific `.mex22` and `.mex24` MAXQDA Exchange formats are retained.

---

## Database Schema

Six tables in `23221189-sq26.db` (SQLite):

**projects** — One row per discovered dataset/collection. Key columns include both the required schema fields (`repository_id`, `repository_url`, `project_url`, `query_string`, `upload_date`, `download_date`, `download_method`, `download_repository_folder`, `download_project_folder`, `language`, `version`) and extended fields (`source_repository`, `source_id`, `title`, `authors` (JSON), `description`, `doi` (full URL), `license`, `keywords` (JSON), `has_qda_files`, `qda_file_count`, `matched_queries` (JSON), `download_status`, `metadata_json`). Unique constraint on `(source_repository, source_id)`.

**files** — One row per file within a project. Columns: `project_id` (FK), `filename`, `file_extension`, `file_type` (extension without dot, e.g. "xlsx"), `file_category` (analysis/primary/additional/unknown), `file_size_bytes`, `download_url`, `checksum`, `download_status`.

**keywords** — Normalized keyword table. Columns: `project_id` (FK), `keyword`. One row per keyword per project.

**person_role** — Normalized person/role table. Columns: `project_id` (FK), `name`, `role` (AUTHOR/CONTACT/UNKNOWN).

**licenses** — Normalized license table. Columns: `project_id` (FK), `license`.

**technical_challenges** — Logs data-related issues encountered during harvesting: `challenge_type` (rate_limit, access_denied, api_error, etc.), `description`, linked to project and repository.

---

## Harvest Results

Results from the most recent harvest run:

| Repository | Projects | Files | QDA Files |
|-----------|----------|-------|-----------|
| Harvard Dataverse | 1,958 | 60,495 | 173 |
| Columbia Oral History | 327 | 737 | 0 |
| **Total** | **2,285** | **61,232** | **173** |

### QDA Files Found

The pipeline discovered **173 QDA analysis files** across **117 projects** on Harvard Dataverse:

| Format | Count | Software |
|--------|-------|----------|
| `.nvp` | 30 | NVivo (older format) |
| `.qdpx` | 27 | REFI-QDA standard (interoperable) |
| `.nvpx` | 27 | NVivo (newer format) |
| `.mtr` | 17 | MAXQDA exported code system |
| `.mx22` | 13 | MAXQDA 2022 |
| `.mx20` | 13 | MAXQDA 2020 |
| `.atlproj` | 10 | ATLAS.ti |
| `.mx5` | 9 | MAXQDA 11 (Windows) |
| `.hpr7` | 7 | ATLAS.ti 7 |
| `.cat` | 6 | Coding Analysis Toolkit |
| `.qdc` | 5 | QDAcity |
| Other | 9 | `.mx24`, `.ppj`, `.mx12`, `.mx3` |

These files were discovered through a combination of dataset-level search (25 queries across 3 tiers) and file-level search (42 QDA extension patterns), which catches datasets containing QDA files even when their metadata doesn't mention QDA terms. Many projects were discovered by multiple queries, demonstrating the value of the expanded query system.

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
rm 23221189-sq26.db
python run_pipeline.py --harvest-only
python export_csv.py
```

The database and downloaded files are gitignored. CSV exports under `exports/` contain the harvested data.

---

## Known Limitations

- **Columbia is a primary data archive, not a QDA repository** — The Columbia Oral History Archive contains oral history recordings and transcripts (qualitative primary data), not QDA analysis project files. The DLC platform doesn't expose direct download URLs — content is streaming-only or requires institutional access. The harvester saves full JSON metadata per project as a permanent record, but media files are marked as `skipped`. Additionally, 93 Columbia projects use the `http://rightsstatements.org/vocab/InC/1.0/` rights statement ("In Copyright" — not an open license). See the "Why Columbia Oral History Has 0 QDA Files" section above for details.

- **QDA files are rare** — Out of 2,285 projects and 61,232 files, only 173 QDA analysis files were found across 117 projects (30 `.nvp`, 27 `.qdpx`, 27 `.nvpx`, 17 `.mtr`, 13 `.mx22`, 13 `.mx20`, 10 `.atlproj`, and others). All from Harvard Dataverse; Columbia Oral History has none. This confirms the hypothesis that QDA project files are rarely shared, which is the gap QDArchive is meant to fill.

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
