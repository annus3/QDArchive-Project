"""
Pipeline configuration — search terms, repository definitions, file extension mappings.
"""

import os


# Paths
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(PROJECT_ROOT, "data")
DB_PATH = os.path.join(PROJECT_ROOT, "23221189-sq26.db")
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
    ".mex",          # MAXQDA exchange (generic)
    ".mtr",          # MAXQDA exported code system (legacy)
    ".loa",          # MAXQDA log analysis
    ".sea",          # MAXQDA survey analysis
    ".mod",          # MAXQDA module

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
                       ".mx", ".mc2", ".mex", ".m2k", ".mtr",
                       ".loa", ".sea", ".mod"))
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

# Tier 1: QDA file extension patterns (highest precision)
# These are NOT sent as dataset-search queries — they feed _build_file_queries()
# in the Dataverse harvester, which already appends *.ext patterns from
# QDA_EXTENSIONS.  Listed here for documentation / potential future use.
QDA_EXTENSION_QUERIES = [f"*{ext}" for ext in sorted(QDA_EXTENSIONS)]

# Tier 2: CAQDAS software tool names (high precision)
TIER2_TOOL_QUERIES = [
    "qdpx",                          # 11 QDA files found
    "REFI-QDA",                      # 3 QDA files found
    "MAXQDA",                        # 10 QDA files found (.mx22, .mx24, .mx20)
    "NVivo",                         # 23 QDA files found (.nvp, .nvpx)
    "ATLAS.ti",                      # 3 QDA files found (.atlproj, .qdpx)
    "QDA Miner",                     # 3 QDA files found (.qdpx)
    "QDAcity",                       # Niche — QDAcity cloud tool
    "f4analyse",                     # Niche — f4analyse transcription/coding tool
    "Dedoose",                       # Cloud-based QDA tool (relevant datasets)
    "Quirkos",                       # Quirkos QDA tool
    "HyperRESEARCH",                 # HyperRESEARCH QDA tool
    "Kwalitan",                      # Kwalitan QDA tool
    "CAQDAS",                        # General CAQDAS term
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
