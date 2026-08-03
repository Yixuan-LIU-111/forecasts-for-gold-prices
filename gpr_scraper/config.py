"""Configuration for GPR (Geopolitical Risk Index) scraper."""

from pathlib import Path

# --- Target URL ---
GPR_PAGE_URL = "https://www.matteoiacoviello.com/gpr.htm"
GPR_EXCEL_URL = "https://www.matteoiacoviello.com/gpr_files/data_gpr_daily_recent.xls"

# --- Request Configuration ---
REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.matteoiacoviello.com/",
}

# --- Rate Limiting ---
MIN_DELAY_SECONDS = 2.0

# --- Retry Configuration ---
MAX_RETRIES = 3
RETRY_BASE_DELAY = 5.0
REQUEST_TIMEOUT = 120

# --- Output ---
OUTPUT_DIR = Path(__file__).resolve().parent.parent / "data"
LOG_DIR = Path(__file__).resolve().parent.parent / "logs"
LOG_FILE = LOG_DIR / "gpr_scraper.log"
LOG_LEVEL = "INFO"

# --- Output files ---
OUTPUT_FILE = OUTPUT_DIR / "gpr_latest.json"
HISTORY_FILE = OUTPUT_DIR / "gpr_history.jsonl"