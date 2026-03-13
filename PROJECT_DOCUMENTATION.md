# QDArchive Seeding Project — Documentation

> **Living document** — this file is continuously updated as the project evolves. Every task, decision, and finding is recorded here.

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [Background & Motivation](#2-background--motivation)
3. [Key Concepts & Terminology](#3-key-concepts--terminology)
4. [Project Parts](#4-project-parts)
   - [Part 1 — Acquisition](#part-1--acquisition)
   - [Part 2 — Classification](#part-2--classification)
   - [Part 3 — Analysis](#part-3--analysis)
5. [Data File Taxonomy](#5-data-file-taxonomy)
6. [Qualitative Data Repositories](#6-qualitative-data-repositories)
7. [QDA File Types & Extensions](#7-qda-file-types--extensions)
8. [Licensing Guidelines](#8-licensing-guidelines)
9. [Acquisition Strategy & Heuristics](#9-acquisition-strategy--heuristics)
10. [Project Structure](#10-project-structure)
11. [Progress Log](#11-progress-log)

---

## 1. Project Overview

**QDArchive** is a web service designed for researchers to **publish and archive qualitative data**, with a particular emphasis on **Qualitative Data Analysis (QDA) files**.

This project — **Seeding QDArchive** — aims to lay the groundwork for populating QDArchive with openly available qualitative research data from the web. The goal is to solve the classic *chicken-and-egg* problem: researchers will not come to an empty archive, so we must **seed** it with high-quality, openly licensed qualitative data and QDA files first.

### Why This Matters

- Qualitative data (interview transcripts, research articles, audio/video, etc.) and QDA files are invaluable for:
  - **Retrieval-Augmented Generation (RAG)** creation
  - **Large Language Model (LLM)** training
- QDArchive is still a **prototype under active development** — seeding it with real data accelerates its development and adoption.

---

## 2. Background & Motivation

| Aspect | Detail |
|--------|--------|
| **What is QDArchive?** | A web service for researchers to publish and archive qualitative data |
| **Current state** | Prototype, under active development |
| **Core problem** | Chicken-and-egg: no researchers without data, no data without researchers |
| **Solution** | Seed the archive with openly available qualitative data from the web |
| **Data of interest** | Qualitative data files + QDA (analysis) files |
| **Downstream use** | RAG creation, LLM training, research reuse |

---

## 3. Key Concepts & Terminology

### Qualitative Data
Non-numerical data that captures meaning, context, and subjective experience. Examples:
- Interview transcripts
- Research articles
- Audio / video recordings
- Field notes, observations

### Qualitative Data Analysis (QDA) Files
Structured data files produced by a researcher when they **analyze/interpret** qualitative data (e.g., coded interview transcripts). These are the **primary files of interest** in this project.

### REFI-QDA Standard
An interoperability standard for QDA files. The canonical format is `.qdpx` — see [qdasoftware.org](https://www.qdasoftware.org/).

### Primary Data Files
The **input** data to a researcher's analysis — e.g., interview transcripts, articles, images.

### Additional Data Files
Any other files a researcher considers part of the project that are **not** analysis or primary data files.

---

## 4. Project Parts

The project is divided into three sequential parts:

### Part 1 — Acquisition

> **Status: Active**

**Objective:** Find and download as many qualitative research projects from the web as possible.

**Key Tasks:**
1. **Discover** qualitative data research projects across repositories and the open web.
2. **Identify** projects by the presence of:
   - Analysis Data files (QDA files) such as `.qdpx`, `.mx24`, etc.
   - Descriptions explicitly mentioning "qualitative (data) research"
3. **Download** entire research project folders (all files) — use this as a basic heuristic.
4. **Collect metadata** — as much as possible for every project.
5. **Verify licensing** — data must have an **open license** (Creative Commons, etc.). No license = do not use.
6. **Catalog** each project with its analysis files, primary files, and additional files.

**What NOT to do:**
- Do not attempt to download entire generic repositories (e.g., all of arXiv).
- "Everything can be interpreted as qualitative data" — stay focused on actual qualitative research projects.

### Part 2 — Classification

> **Status: Not Started**

*(Details to be added as the project progresses.)*

### Part 3 — Analysis

> **Status: Not Started**

*(Details to be added as the project progresses.)*

---

## 5. Data File Taxonomy

Every qualitative research project may contain three categories of files:

### 5.1 Analysis Data Files (QDA Files)

| Property | Detail |
|----------|--------|
| **What** | Structured data capturing a researcher's interpretation of primary data |
| **Expected count** | 0 or 1 per project (most likely), but can be > 1 |
| **Key extensions** | `.qdpx`, `.mx24`, and others (see [Section 7](#7-qda-file-types--extensions)) |
| **Note** | May contain none, some, or all primary data files embedded within |

### 5.2 Primary Data Files

| Property | Detail |
|----------|--------|
| **What** | Input data used by the researcher for analysis (e.g., interview transcripts, papers) |
| **Expected count** | 0 to n per project |
| **Key extensions** | `.pdf`, `.doc`, `.docx`, `.txt`, `.jpg`, `.mp3`, `.mp4`, etc. (anything goes) |
| **Note** | May be embedded inside an analysis file AND/OR exist as standalone files |

### 5.3 Additional Data Files

| Property | Detail |
|----------|--------|
| **What** | Any other files the researcher considers part of the project |
| **Expected count** | 0 to n (no expectations) |
| **Key extensions** | `.pdf`, `.doc`, `.docx`, `.txt`, `.jpg`, etc. (anything goes) |
| **Note** | Collect these as well |

---

## 6. Qualitative Data Repositories

The following repositories and data sources are targets for acquisition. This list is **actively maintained** — add new sources as they are discovered.

### Tier 1 — Primary Targets (Known QDA / Qualitative Data Repositories)

| # | Name | URL | Example Search | Notes |
|---|------|-----|---------------|-------|
| 1 | **Zenodo** | [zenodo.org](https://zenodo.org/) | [Search: qdpx](https://zenodo.org/search?q=qdpx) | Major open-access repository |
| 2 | **Dryad** | [datadryad.org](http://datadryad.org/) | [Search: qualitative research](https://datadryad.org/search?q=qualitative+research) | |
| 3 | **UK Data Service** | [ukdataservice.ac.uk](https://ukdataservice.ac.uk/learning-hub/qualitative-data/) | [Search: qualitative data](https://datacatalogue.ukdataservice.ac.uk/searchresults?search=qualitative+data) | |
| 4 | **Syracuse QDR** | [qdr.syr.edu](https://qdr.syr.edu/) | [Search: interview](https://data.qdr.syr.edu/dataverse/main/?q=interview) | Qualitative Data Repository |
| 5 | **DANS** | [dans.knaw.nl](https://dans.knaw.nl/en/) | [Search: qdpx](https://ssh.datastations.nl/dataverse/root?q=qdpx) | Search by data station (multiple repos) |
| 6 | **DataverseNO** | [dataverse.no](https://dataverse.no/dataverse.xhtml) | [Search: qdpx](https://dataverse.no/dataverse/root/?q=qdpx) | Dataverse-based (similar software to DANS) |
| 7 | **ADA** | [ada.edu.au](https://ada.edu.au/) | [Search: codebook](https://dataverse.ada.edu.au/dataverse/ada/?q=codebook) | Australian Data Archive |
| 8 | **SADA / DataFirst** | [datafirst.uct.ac.za](https://datafirst.uct.ac.za/) | [Search: interview](https://www.datafirst.uct.ac.za/dataportal/index.php/catalog?sk=interview) | South African Data Archive |
| 9 | **IHSN** | [ihsn.org](https://ihsn.org/) | — | International Household Survey Network |
| 10 | **Harvard Dataverse** | [dataverse.harvard.edu](https://dataverse.harvard.edu/) | [Search: qdpx](https://dataverse.harvard.edu/dataverse/harvard?q=qdpx) | |
| 11 | **Finnish Social Science Data Archive (FSD)** | [fsd.tuni.fi](https://www.fsd.tuni.fi/en) | [Search: qualitative](https://services.fsd.tuni.fi/catalogue/index?limit=50&study_language=en&lang=en&page=0&field=publishing_date&direction=descending&data_kind_string_facet=Qualitative) | |
| 12 | **AUSSDA** | [aussda.at](https://aussda.at/en/) | [Search: qualitative](https://data.aussda.at/dataverse/AUSSDA/?q=qualitative) | Austrian Social Science Data Archive |
| 13 | **CESSDA** | [cessda.eu](https://www.cessda.eu/Tools/Data-Catalogue) | [Search: qualitative](https://datacatalogue.cessda.eu/?query=qualitative) | Consortium of European Social Science Data Archives |
| 14 | **Databrary** | [databrary.org](https://databrary.org/) | [Search: qualitative](https://databrary.org/search?q=qualitative&tab=0) | Behavioral science data |
| 15 | **ICPSR** | [icpsr.umich.edu](https://icpsr.umich.edu) | [Search: interview](https://www.icpsr.umich.edu/web/ICPSR/search/studies?q=interview) | Inter-university Consortium for Political and Social Research |

### Tier 2 — Additional Sources (To Be Explored)

| # | Name / URL | Notes |
|---|-----------|-------|
| 16 | [opendata.uni-halle.de](https://opendata.uni-halle.de/) | University of Halle open data |
| 17 | [cis.es/estudios/catalogo-estudios](https://www.cis.es/estudios/catalogo-estudios) | Spanish research center |
| 18 | [murray.harvard.edu](https://www.murray.harvard.edu/) | Harvard Murray Research Archive |
| 19 | [Columbia Oral History](https://guides.library.columbia.edu/oral_history/digital_collections) | Digital oral history collections |
| 20 | [Sikt (Norway)](https://sikt.no/en/find-data) | Norwegian data discovery |

### Tier 3 — Networks & General Sources

| Name | URL | Notes |
|------|-----|-------|
| **QualiData Network** | [qualidatanet.com](https://www.qualidatanet.com/en/) | Network of qualitative data archives |
| **Qualiservice** | [qualidatanet.com (Qualiservice)](https://www.qualidatanet.com/de/ueber-uns/articles/das-netzwerk-detail.html) | Part of QualiData Network |
| **QualiBi** | [qualidatanet.com (QualiBi)](https://www.qualidatanet.com/de/ueber-uns/articles/verbundpartner-werden.html) | Partner of QualiData Network |
| Individual uploads | Use search engines (Google, Google Dataset Search) | Search for QDA file types directly |
| Generic file shares | Google Drive, Dropbox, FileShare, etc. | Ad-hoc discovery |

---

## 7. QDA File Types & Extensions

These are the known file extensions for Analysis Data (QDA) files:

| Extension | Software / Format | Notes |
|-----------|------------------|-------|
| `.qdpx` | REFI-QDA (interoperability standard) | **Primary target** — see [qdasoftware.org](https://www.qdasoftware.org/) |
| `.mx24` | MAXQDA 24 | MAXQDA project file |
| *(more to be added)* | *(see file extensions spreadsheet)* | Expand this list as new types are discovered |

> **Action Item:** Obtain and integrate the full file extensions spreadsheet into this document.

---

## 8. Licensing Guidelines

### Rules

| Condition | Action |
|-----------|--------|
| **Creative Commons (any variant)** | ✅ Include — this is the ideal case |
| **Other open licenses** | ✅ Include — evaluate on a case-by-case basis |
| **No license specified** | ❌ **Do NOT use** — treat as closed/proprietary |
| **Proprietary / restricted** | ❌ **Do NOT use** |

### Notes
- **Always collect the license** as part of metadata.
- Finding a license may be difficult for some repositories — document the effort.
- When in doubt, err on the side of exclusion.

---

## 9. Acquisition Strategy & Heuristics

### Basic Approach
1. **Search repositories** from the list in [Section 6](#6-qualitative-data-repositories) using keywords:
   - `qdpx`, `qualitative research`, `qualitative data`, `interview transcript`, `codebook`, specific QDA file extensions
2. **For each matching project:**
   - Download the **entire research project folder** (all files).
   - Record all available **metadata** (title, authors, description, license, date, DOI, etc.).
   - Classify files into: Analysis Data, Primary Data, Additional Data.
   - Verify and record the **license**.
3. **Prioritize** projects that contain actual QDA/analysis files over those with only primary data.
4. **Expand** to search engines and generic file shares if repository searches are exhausted.

### Search Keywords
- `qdpx`
- `qualitative data analysis`
- `qualitative research`
- `interview transcript`
- `codebook`
- `thematic analysis`
- `grounded theory`
- Specific software names: `MAXQDA`, `NVivo`, `ATLAS.ti`, `QDA Miner`

### Metadata to Collect
For each project, capture at minimum:
- Title
- Authors / Contributors
- Description / Abstract
- License
- Date of publication
- DOI or persistent identifier
- Source repository
- File manifest (list of all files with types and sizes)
- Keywords / Tags

---

## 10. Project Structure

```
QDArchive-Project/
├── PROJECT_DOCUMENTATION.md    # This file — living documentation
├── .gitignore                  # Git ignore rules
├── data/                       # Downloaded research project data (gitignored)
│   ├── raw/                    # Raw downloads organized by source
│   └── processed/              # Processed/organized data
├── metadata/                   # Collected metadata files
├── scripts/                    # Acquisition, classification, analysis scripts
├── reports/                    # Generated reports and summaries
└── README.md                   # Public-facing project README (to be created)
```

> This structure will evolve as Parts 2 and 3 begin.

---

## 11. Progress Log

| Date | Task | Status | Notes |
|------|------|--------|-------|
| 2026-03-13 | Project initialized | ✅ Done | Created documentation, .gitignore, connected to GitHub |
| | Part 1 — Acquisition | 🔄 In Progress | Starting repository discovery |

---

*Last updated: 2026-03-13*
