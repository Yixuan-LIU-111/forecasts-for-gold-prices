"""Configuration for VIX scraper."""

from pathlib import Path

# --- Target URLs ---
CBOE_VIX_URL = "https://www.cboe.com/tradable-products/vix"
CBOE_VIX_DASHBOARD_URL = "https://www.cboe.com/us/indices/dashboard/VIX/"

# --- Request Configuration ---
REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer": "https://www.cboe.com/",
}

# --- Rate Limiting ---
MIN_DELAY_SECONDS = 2.0

# --- Retry Configuration ---
MAX_RETRIES = 3
RETRY_BASE_DELAY = 2.0

# --- Playwright Configuration ---
PLAYWRIGHT_TIMEOUT_MS = 30000
PLAYWRIGHT_WAIT_MS = 5000

# --- Output ---
OUTPUT_DIR = Path(__file__).resolve().parent.parent / "data"
OUTPUT_FILE = OUTPUT_DIR / "vix_latest.json"
HISTORY_FILE = OUTPUT_DIR / "vix_history.jsonl"

# --- Logging ---
LOG_DIR = Path(__file__).resolve().parent.parent / "logs"
LOG_FILE = LOG_DIR / "vix_scraper.log"
LOG_LEVEL = "INFO"