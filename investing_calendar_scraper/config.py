"""Configuration for Investing.com economic calendar scraper."""

from pathlib import Path

# --- Target URLs ---
# The calendar widget endpoint used by Investing.com webmaster tools.
# It returns an HTML table with economic events for the requested period.
CALENDAR_IFRAME_URL = (
    "https://sslecal2.investing.com/"
    "?columns=exc_flags,exc_currency,exc_importance,exc_actual,exc_forecast,exc_previous"
    "&features=datepicker,timezone"
    "&calType=week"
    "&timeZone=8"
    "&lang=1"
)

# --- Request Configuration ---
REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Referer": "https://cn.investing.com/economic-calendar",
}

# --- Rate Limiting ---
MIN_DELAY_SECONDS = 1.0

# --- Retry Configuration ---
MAX_RETRIES = 3
RETRY_BASE_DELAY = 2.0
REQUEST_TIMEOUT = 60

# --- Filters ---
# Target importance level on the page: 1=low, 2=medium, 3=high.
TARGET_IMPORTANCE = "High"

# Target categories as shown on the Investing.com filter panel.
# Because the server-side category filter is protected by Cloudflare,
# we approximate it client-side using keywords (see parser.CATEGORY_KEYWORDS).
TARGET_CATEGORIES = ["employment", "inflation", "economic_activity", "central_banks"]

# --- Output ---
OUTPUT_DIR = Path(__file__).resolve().parent.parent / "data"
OUTPUT_FILE = OUTPUT_DIR / "investing_calendar_latest.json"
HISTORY_FILE = OUTPUT_DIR / "investing_calendar_history.jsonl"
CSV_FILE = OUTPUT_DIR / "investing_calendar_latest.csv"

# --- Logging ---
LOG_DIR = Path(__file__).resolve().parent.parent / "logs"
LOG_FILE = LOG_DIR / "investing_calendar_scraper.log"
LOG_LEVEL = "INFO"
