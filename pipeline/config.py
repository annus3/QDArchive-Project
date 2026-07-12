"""
Pipeline configuration — search terms, repository definitions, file extension mappings.
"""

import os


# Paths
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(PROJECT_ROOT, "data")
# Operational DB: carries all extras (technical_challenges, extra columns,
# analytics). Used by harvesters, downloaders, exports.
DB_PATH = os.path.join(PROJECT_ROOT, "23221189-sq26-full.db")
# Submission DB: stripped to the sq26-grading required schema. Built by
# sub_db.py from the operational DB. This is the file the
# grader evaluates — filename must match ^\d{8}-(?:seeding|sq26)\.db$.
SUBMISSION_DB_PATH = os.path.join(PROJECT_ROOT, "23221189-sq26.db")
EXPORTS_DIR = os.path.join(PROJECT_ROOT, "exports")


# QDA (Analysis Data) file extensions
QDA_EXTENSIONS = {
    # REFI-QDA standard

    ".qdpx",         # REFI-QDA interoperability standard

    # MAXQDA  (https://www.maxqda.com/help/technical-data-and-information/file-management)
    ".mqda",         # MAXQDA current project file
    ".mqbac",        # MAXQDA backup project file
    ".mqtc",         # MAXQDA TeamCloud project file
    ".mqex",         # MAXQDA Exchange file
    ".mqmtr",        # MAXQDA exported code system
    ".mx24",         # MAXQDA 24 project file
    ".mx24bac",      # MAXQDA 24 backup
    ".mc24",         # MAXQDA 24 TeamCloud
    ".mex24",        # MAXQDA 24 Exchange file
    ".mx22",         # MAXQDA 2022 project file
    ".mex22",        # MAXQDA 22 Exchange file
    ".mx20",         # MAXQDA 2020 project file
    ".mx18",         # MAXQDA 2018 project file
    ".mx12",         # MAXQDA 12 project file
    ".mx11",         # MAXQDA 11 macOS
    ".mx5",          # MAXQDA 11 Windows
    ".mx4",          # MAXQDA 10
    ".mx3",          # MAXQDA 2007
    ".mx2",          # MAXQDA 2
    ".m2k",          # MAXQDA 1
    ".mtr",          # MAXQDA exported code system (legacy)
    ".loa",          # MAXQDA log analysis
    ".sea",          # MAXQDA survey analysis

    # NVivo  (https://lumivero.com/products/nvivo/)
    ".nvp",          # NVivo (older)
    ".nvpx",         # NVivo (newer)

    # ATLAS.ti
    ".atlasproj",    # ATLAS.ti (official extension name)
    ".atlproj",      # ATLAS.ti 22+ (short form seen in the wild)
    ".hpr",          # ATLAS.ti hermeneutic unit (older)
    ".hpr7",         # ATLAS.ti 7 hermeneutic unit
    ".hermeneutic",  # ATLAS.ti legacy hermeneutic unit

    # QDAcity
    ".qdc",          # QDAcity project file

    # QDA Miner  (Provalis Research)
    ".qda",          # QDA Miner project
    ".ppj",          # QDA Miner project (older)
    ".pprj",         # QDA Miner project (newer)
    ".qlt",          # QDA Miner Lite

    # f4analyse
    ".f4p",          # f4analyse project file

    # Quirkos
    ".qpd",          # Quirkos project (official)
    ".qde",          # Quirkos (alternate)

    # Other
    ".cat",          # Coding Analysis Toolkit
    ".hnsp",         # HyperRESEARCH
    ".kdp",          # Kwalitan
}

# Subset: MAXQDA-specific extensions (used for maxqda_file_count)
MAXQDA_EXTENSIONS = {
    ext for ext in QDA_EXTENSIONS
    if ext.startswith((".mqda", ".mqb", ".mqt", ".mqe", ".mqm",
                       ".mx", ".mc2", ".mex2", ".m2k", ".mtr",
                       ".loa", ".sea"))
}

# Common primary data extensions (for classification)
PRIMARY_DATA_EXTENSIONS = {
    ".pdf", ".doc", ".docx", ".txt", ".rtf", ".odt",
    ".csv", ".tsv", ".xlsx", ".xls",
    ".jpg", ".jpeg", ".png", ".gif", ".tif", ".tiff", ".bmp",
    ".mp3", ".wav", ".m4a", ".ogg", ".flac", ".aac",
    ".mp4", ".avi", ".mov", ".mkv", ".wmv", ".webm",
    ".html", ".htm", ".xml", ".json",
}


# 3-tier search query system
#
# NOTE ON SIMILAR NAMES ACROSS TIERS:
# Some terms appear in both Tier 1 and Tier 2 (e.g. "qdpx" in Tier 2
# and "*.qdpx" in Tier 1).  These are NOT redundant — they hit
# different Dataverse API endpoints:
#
#   Tier 1 (*.qdpx)  →  type=file search  →  matches by FILENAME
#   Tier 2 ("qdpx")  →  type=dataset search  →  matches by METADATA text
#
# A dataset may mention "qdpx" in its description but have no .qdpx file,
# or it may contain a .qdpx file without ever mentioning the word in its
# metadata.  Both searches are needed for full coverage.

# Tier 1: QDA file extension patterns (highest precision)
# These are NOT sent as dataset-search queries — they feed _build_file_queries()
# in the Dataverse harvester, which already appends *.ext patterns from
# QDA_EXTENSIONS.  Listed here for documentation / potential future use.
QDA_EXTENSION_QUERIES = [f"*{ext}" for ext in sorted(QDA_EXTENSIONS)]

# Tier 2: CAQDAS software tool names (high precision)
# These search dataset METADATA for tool names.  Even when a name
# overlaps with a Tier 1 extension (e.g. "qdpx"), the search target
# is different (metadata text vs. filename).
TIER2_TOOL_QUERIES = [
    "qdpx",                          # 11 QDA files found  (also *.qdpx in Tier 1 — Tier 1 matches filenames, this matches metadata)
    "REFI-QDA",                      # 3 QDA files found   (the standard's name — catches metadata that says "REFI-QDA" but files may not be .qdpx)
    "MAXQDA",                        # 10 QDA files found   (also *.mx* in Tier 1 — this finds datasets mentioning the tool by name)
    "NVivo",                         # 23 QDA files found   (also *.nvp/*.nvpx in Tier 1)
    "ATLAS.ti",                      # 3 QDA files found    (also *.atlproj etc. in Tier 1)
    "QDA Miner",                     # 3 QDA files found    (also *.qda/*.ppj in Tier 1)
    "QDAcity",                       # Niche — QDAcity cloud tool  (also *.qdc in Tier 1)
    "f4analyse",                     # Niche — f4analyse tool  (also *.f4p in Tier 1)
    "Dedoose",                       # Cloud-based QDA tool (no local file format — Tier 2 only)
    "Quirkos",                       # Quirkos QDA tool  (also *.qpd/*.qde in Tier 1)
    "HyperRESEARCH",                 # HyperRESEARCH QDA tool  (also *.hnsp in Tier 1)
    "Kwalitan",                      # Kwalitan QDA tool  (also *.kdp in Tier 1)
    "CAQDAS",                        # General CAQDAS term (no matching extension — Tier 2 only)
]

# Tier 3: Methodology keywords (broader recall)
TIER3_METHODOLOGY_QUERIES = [
    '"qualitative data analysis"',   # 1 QDA file found (.qdpx)
    '"thematic analysis"',           # 1 QDA file found (.nvp)
    '"grounded theory"',
    '"qualitative coding"',
    '"qualitative research data"',
    '"interview transcripts"',
    '"focus group transcripts"',
    '"narrative analysis"',
    '"discourse analysis"',
    '"content analysis" qualitative',
    '"ethnographic data"',
    '"qualitative interviews"',
]

# Combined flat list (backward-compatible default)
SEARCH_QUERIES = TIER2_TOOL_QUERIES + TIER3_METHODOLOGY_QUERIES


# Repository configurations
REPOSITORIES = {
    # Harvard Dataverse 
    "harvard_dataverse": {
        "type": "dataverse",
        "name": "Harvard Dataverse",
        "base_url": "https://dataverse.harvard.edu",
        "repository_id": 10,
        "rate_limit_seconds": 2.0,
        "enabled": True,
    },

    # Columbia Oral History Archive 
    "columbia_oral_history": {
        "type": "columbia",
        "name": "Columbia Oral History Archive",
        "base_url": "https://dlc.library.columbia.edu",
        "repository_id": 19,
        "rate_limit_seconds": 2.0,
        "enabled": True,
    },
}

# Download settings
MAX_FILE_SIZE_MB = 0            # 0 = no limit (download all files regardless of size)
MAX_TOTAL_DOWNLOAD_GB = 6       # Global download budget in GB (0 = no limit)
DOWNLOAD_TIMEOUT_SECONDS = 600  # Per-file download timeout (10 min)
DOWNLOAD_CHUNK_SIZE = 8192      # Bytes per chunk when streaming
MAX_RETRIES = 3                 # Retry count for failed downloads
MAX_RESULTS_PER_QUERY = 250     # Max records to fetch per search query (cap pagination)
BATCH_COMMIT_SIZE = 50          # Commit to DB every N operations (batch writes)
PROGRESS_FILE = os.path.join(PROJECT_ROOT, "qdarchive.progress.json")


# ─────────────────────────────────────────────────────────────────────────────
# Phase 2 — Classification settings
# (see docs/CLASSIFICATION_RESEARCH.md)
# ─────────────────────────────────────────────────────────────────────────────

# PROJECT_TYPE enum values (spec Step 1). Derived from file categories only.
PROJECT_TYPE_QDA = "QDA_PROJECT"
PROJECT_TYPE_QD = "QD_PROJECT"
PROJECT_TYPE_OTHER = "OTHER_PROJECT"
PROJECT_TYPE_NONE = "NOT_A_PROJECT"
PROJECT_TYPES = (PROJECT_TYPE_QDA, PROJECT_TYPE_QD, PROJECT_TYPE_OTHER, PROJECT_TYPE_NONE)

# Only these project types get an ISIC classification (spec Step 3).
CLASSIFIABLE_TYPES = (PROJECT_TYPE_QDA, PROJECT_TYPE_QD)

# ISIC Rev. 5 division taxonomy artifact (built by build_isic_taxonomy.py from
# docs/ISIC5_Exp_Notes_11Mar2024.xlsx). Committed under a non-git-ignored path.
ISIC_TAXONOMY_PATH = os.path.join(PROJECT_ROOT, "pipeline", "data", "isic_taxonomy.json")

# A runner-up division is reported as secondary_class only if its cosine
# similarity is at least this fraction of the best score (else it is noise).
SECONDARY_MIN_RATIO = 0.6

# Minimum cosine similarity for the primary division. Below this the project/file
# is left unclassified (NULL) rather than forced into a weak bucket — implements
# the "no default bucket / low-confidence → NULL" policy (CLASSIFICATION_RESEARCH
# §10.2). Configurable; 0.0 disables the floor (only zero-overlap → NULL).
MIN_PRIMARY_CONFIDENCE = 0.05

# Number of top TF-IDF terms kept as searchable tags per project.
CLASSIFICATION_TAG_COUNT = 8

# Derived classification database (spec Step 4a). Built from the operational DB
# by sub_db.build_classification_db(); git-tagged `classification-results`.
CLASSIFICATION_DB_PATH = os.path.join(PROJECT_ROOT, "23221189-sq26-classification.db")

