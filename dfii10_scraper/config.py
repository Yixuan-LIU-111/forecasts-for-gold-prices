"""Configuration for DFII10 (TIPS 10-Year) scraper from FRED."""

from pathlib import Path

# --- Target URL ---
FRED_PAGE_URL = "https://fred.stlouisfed.org/series/DFII10"
# Direct CSV download URL (full history)
CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DFII10&cosd=2003-01-02&coed=2026-07-28"

# --- Request Configuration ---
REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://fred.stlouisfed.org/",
}

# --- Rate Limiting ---
MIN_DELAY_SECONDS = 2.0

# --- Retry Configuration ---
# 受限网络下 curl 可能长时间挂起：缩短重试次数与退避，使因子采集在不可达时
# 快速失败（而非阻塞数分钟），避免拖累后台调度器其余任务。
MAX_RETRIES = 2
RETRY_BASE_DELAY = 3.0
REQUEST_TIMEOUT = 20

# --- Output ---
OUTPUT_DIR = Path(__file__).resolve().parent.parent / "data"
LOG_DIR = Path(__file__).resolve().parent.parent / "logs"
LOG_FILE = LOG_DIR / "dfii10_scraper.log"
LOG_LEVEL = "INFO"

# --- Output files ---
OUTPUT_FILE = OUTPUT_DIR / "dfii10_latest.json"
HISTORY_FILE = OUTPUT_DIR / "dfii10_history.jsonl"