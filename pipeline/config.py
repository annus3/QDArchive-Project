"""
Pipeline configuration — search terms, repository definitions, file extension mappings.
"""

import os

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(PROJECT_ROOT, "data")
DB_PATH = os.path.join(PROJECT_ROOT, "qdarchive.db")
EXPORTS_DIR = os.path.join(PROJECT_ROOT, "exports")

# ---------------------------------------------------------------------------
# QDA (Analysis Data) file extensions
# ---------------------------------------------------------------------------
QDA_EXTENSIONS = {
    ".qdpx",     # REFI-QDA interoperability standard
    ".mx24",     # MAXQDA 24
    ".mx22",     # MAXQDA 22
    ".mx20",     # MAXQDA 20
    ".mx18",     # MAXQDA 18
    ".mx12",     # MAXQDA 12
    ".mex",      # MAXQDA exchange
    ".nvp",      # NVivo (older)
    ".nvpx",     # NVivo (newer)
    ".hpr",      # ATLAS.ti (older)
    ".atlproj",  # ATLAS.ti 22+
    ".qda",      # QDA Miner
    ".cat",      # Coding Analysis Toolkit
    ".hermeneutic",  # Hermeneutic Unit (ATLAS.ti legacy)
    ".hnsp",     # HyperRESEARCH
    ".kdp",      # Kwalitan
    ".qde",      # Quirkos
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

# ---------------------------------------------------------------------------
# Search queries — used across all harvesters
# ---------------------------------------------------------------------------
SEARCH_QUERIES = [
    "qdpx",
    "qualitative data analysis",
    "qualitative research data",
    "MAXQDA",
    "NVivo qualitative",
    "ATLAS.ti qualitative",
    "interview transcript qualitative",
    "thematic analysis data",
    "grounded theory data",
    "codebook qualitative",
]

# ---------------------------------------------------------------------------
# Repository configurations
# ---------------------------------------------------------------------------
REPOSITORIES = {
    # ── Harvard Dataverse (Dataset 10) ──────────────────────────────────
    "harvard_dataverse": {
        "type": "dataverse",
        "name": "Harvard Dataverse",
        "base_url": "https://dataverse.harvard.edu",
        "rate_limit_seconds": 2.0,
        "enabled": True,
    },

    # ── Columbia Oral History Archive (Dataset 19) ──────────────────────
    "columbia_oral_history": {
        "type": "columbia",
        "name": "Columbia Oral History Archive",
        "base_url": "https://dlc.library.columbia.edu",
        "rate_limit_seconds": 2.0,
        "enabled": True,
    },
}

# ---------------------------------------------------------------------------
# Download settings
# ---------------------------------------------------------------------------
MAX_FILE_SIZE_MB = 500          # Skip files larger than this (MB)
DOWNLOAD_TIMEOUT_SECONDS = 300  # Per-file download timeout
DOWNLOAD_CHUNK_SIZE = 8192      # Bytes per chunk when streaming
MAX_RETRIES = 3                 # Retry count for failed downloads
MAX_RESULTS_PER_QUERY = 250     # Max records to fetch per search query (cap pagination)
