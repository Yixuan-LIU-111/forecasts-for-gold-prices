"""Configuration for EPU Daily Index scraper."""

from pathlib import Path

# --- Target URL ---
PAGE_URL = "http://www.policyuncertainty.com/us_monthly.html"
CSV_URL = "http://www.policyuncertainty.com/media/All_Daily_Policy_Data.csv"

# --- Request Configuration ---
REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "text/csv,application/csv,*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "http://www.policyuncertainty.com/us_monthly.html",
}

# --- Rate Limiting ---
MIN_DELAY_SECONDS = 2.0

# --- Retry Configuration ---
MAX_RETRIES = 3
RETRY_BASE_DELAY = 5.0
REQUEST_TIMEOUT = 60

# --- Output ---
OUTPUT_DIR = Path(__file__).resolve().parent.parent / "data"
LOG_DIR = Path(__file__).resolve().parent.parent / "logs"
LOG_FILE = LOG_DIR / "epu_scraper.log"
LOG_LEVEL = "INFO"

# --- Output files ---
OUTPUT_FILE = OUTPUT_DIR / "epu_daily_latest.json"
HISTORY_FILE = OUTPUT_DIR / "epu_daily_history.jsonl"