"""Scrape DFII10 (TIPS 10-Year) data from FRED via CSV download."""

import csv
import io
import logging
import os
import subprocess
import time
from typing import Optional

from config import CSV_URL, MAX_RETRIES, RETRY_BASE_DELAY

logger = logging.getLogger(__name__)

# Fallback CSV file path (pre-downloaded via curl outside sandbox)
_FALLBACK_CSV_PATH = "/tmp/dfii10_data.csv"


def _download_via_curl() -> Optional[str]:
    """Download CSV using curl via subprocess.

    curl is used because Python's http.client/requests time out
    due to sandbox restrictions on the macOS LibreSSL stack.

    Returns:
        Raw CSV text, or None on failure.
    """
    for attempt in range(MAX_RETRIES):
        try:
            time.sleep(RETRY_BASE_DELAY if attempt > 0 else 2.0)

            result = subprocess.run(
                [
                    "curl", "-s", "--max-time", "120",
                    "-H", "User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
                    CSV_URL,
                ],
                capture_output=True,
                text=True,
                timeout=180,
            )

            if result.returncode != 0 or not result.stdout:
                logger.warning("Attempt %d/%d: curl returned empty", attempt + 1, MAX_RETRIES)
                if attempt == MAX_RETRIES - 1:
                    return None
                time.sleep(RETRY_BASE_DELAY * (2 ** attempt))
                continue

            lines = result.stdout.splitlines()
            if len(lines) < 2:
                logger.warning("Attempt %d/%d: insufficient data (%d lines)",
                               attempt + 1, MAX_RETRIES, len(lines))
                if attempt == MAX_RETRIES - 1:
                    return None
                time.sleep(RETRY_BASE_DELAY * (2 ** attempt))
                continue

            logger.info("CSV downloaded via curl: %d lines", len(lines))
            return result.stdout

        except subprocess.TimeoutExpired:
            logger.warning("Attempt %d/%d timed out", attempt + 1, MAX_RETRIES)
            if attempt == MAX_RETRIES - 1:
                return None
            time.sleep(RETRY_BASE_DELAY * (2 ** attempt))
        except Exception as e:
            logger.warning("Attempt %d/%d failed: %s", attempt + 1, MAX_RETRIES, e)
            if attempt == MAX_RETRIES - 1:
                return None
            time.sleep(RETRY_BASE_DELAY * (2 ** attempt))

    return None


def _read_fallback_csv() -> Optional[str]:
    """Read CSV from a pre-downloaded fallback file.

    The file can be created by running:
        curl -s -o /tmp/dfii10_data.csv "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DFII10&cosd=2003-01-02&coed=2026-07-28"

    Returns:
        Raw CSV text, or None if file not found.
    """
    if not os.path.exists(_FALLBACK_CSV_PATH):
        return None
    try:
        with open(_FALLBACK_CSV_PATH, "r", encoding="utf-8-sig") as f:
            content = f.read()
        logger.info("Read fallback CSV: %d bytes, %d lines",
                    len(content), len(content.splitlines()))
        return content
    except Exception as e:
        logger.warning("Failed to read fallback CSV: %s", e)
        return None


def fetch_csv() -> Optional[str]:
    """Fetch the DFII10 CSV content.

    Tries:
        1. Pre-downloaded fallback file (fastest)
        2. curl via subprocess (works in sandbox when curl has network access)

    Returns:
        Raw CSV text, or None on failure.
    """
    # Try fallback file first
    content = _read_fallback_csv()
    if content:
        return content

    # Try curl
    logger.info("No fallback CSV found, trying curl download")
    content = _download_via_curl()
    if content:
        # Cache for future use
        try:
            with open(_FALLBACK_CSV_PATH, "w", encoding="utf-8") as f:
                f.write(content)
        except Exception:
            pass
        return content

    return None


def parse_csv(content: str) -> Optional[dict]:
    """Parse the DFII10 CSV content and extract all data + latest record.

    CSV format:
        observation_date,DFII10
        2003-01-02,2.43
        ...
        2026-07-27,2.44

    Args:
        content: Raw CSV text.

    Returns:
        Dict with summary stats and latest data point, or None on failure.
    """
    if not content:
        return None

    reader = csv.DictReader(io.StringIO(content))

    rows = []
    for row in reader:
        date = row.get("observation_date", "").strip()
        value_raw = row.get("DFII10", "").strip()

        if not date:
            continue

        value = None
        if value_raw:
            try:
                value = float(value_raw)
            except ValueError:
                pass

        rows.append({"date": date, "value": value})

    if not rows:
        logger.error("No data rows found in CSV")
        return None

    valid_rows = [r for r in rows if r["value"] is not None]

    if not valid_rows:
        logger.error("No valid data rows found in CSV")
        return None

    latest = valid_rows[-1]
    values = [r["value"] for r in valid_rows]

    result = {
        "series_id": "DFII10",
        "series_name": "10-Year TIPS Yield",
        "source": "FRED (Federal Reserve Economic Data)",
        "latest_date": latest["date"],
        "latest_value": latest["value"],
        "total_observations": len(rows),
        "valid_observations": len(valid_rows),
        "date_range": {
            "start": valid_rows[0]["date"],
            "end": valid_rows[-1]["date"],
        },
        "stats": {
            "min": round(min(values), 4),
            "max": round(max(values), 4),
            "mean": round(sum(values) / len(values), 4),
        },
        "recent_data": [r for r in valid_rows[-30:]],
    }

    logger.info("DFII10 parsed: latest=%s value=%.2f, total=%d rows",
                latest["date"], latest["value"], len(valid_rows))
    return result


def scrape_dfii10() -> Optional[dict]:
    """Scrape the latest DFII10 data from FRED.

    Returns:
        Dict with parsed data, or None on failure.
    """
    logger.info("Fetching DFII10 data from FRED")

    csv_content = fetch_csv()
    if not csv_content:
        logger.error("No CSV content retrieved")
        return None

    data = parse_csv(csv_content)
    if data is None:
        logger.error("Failed to parse DFII10 data")
        return None

    data["scraped_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime())

    logger.info("DFII10 data extracted: latest=%s value=%.2f",
                data.get("latest_date"), data.get("latest_value"))
    return data