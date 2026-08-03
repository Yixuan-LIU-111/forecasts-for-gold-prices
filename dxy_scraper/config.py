"""Configuration for DXY (Dollar Index) scraper from Sina Finance."""

from pathlib import Path

# --- Target URL ---
SINA_DXY_URL = "https://gu.sina.cn/quotes/fx/DINIW"

# --- Request Configuration ---
REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.5",
    "Referer": "https://gu.sina.cn/",
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
LOG_DIR = Path(__file__).resolve().parent.parent / "logs"
LOG_FILE = LOG_DIR / "dxy_scraper.log"
LOG_LEVEL = "INFO"

# --- Output files ---
OUTPUT_FILE = OUTPUT_DIR / "dxy_sina_latest.json"
HISTORY_FILE = OUTPUT_DIR / "dxy_sina_history.jsonl"