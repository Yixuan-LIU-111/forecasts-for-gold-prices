"""Scrape EPU Daily Index from policyuncertainty.com."""

import csv
import io
import logging
import time
from typing import Optional

import requests

from config import (
    CSV_URL,
    REQUEST_HEADERS,
    MIN_DELAY_SECONDS,
    MAX_RETRIES,
    RETRY_BASE_DELAY,
    REQUEST_TIMEOUT,
)

logger = logging.getLogger(__name__)


def fetch_csv() -> Optional[str]:
    """Download the EPU Daily CSV file with retry logic.

    Returns:
        Raw CSV text, or None on failure.
    """
    for attempt in range(MAX_RETRIES):
        try:
            time.sleep(RETRY_BASE_DELAY if attempt > 0 else MIN_DELAY_SECONDS)

            resp = requests.get(
                CSV_URL,
                headers=REQUEST_HEADERS,
                timeout=REQUEST_TIMEOUT,
            )
            resp.raise_for_status()
            resp.encoding = "utf-8"

            lines = resp.text.splitlines()
            logger.info("CSV downloaded: %d bytes, %d lines",
                        len(resp.content), len(lines))
            return resp.text

        except requests.exceptions.Timeout:
            logger.warning("Attempt %d/%d timed out", attempt + 1, MAX_RETRIES)
            if attempt == MAX_RETRIES - 1:
                return None
            time.sleep(RETRY_BASE_DELAY * (2 ** attempt))
        except requests.exceptions.RequestException as e:
            logger.warning("Attempt %d/%d failed: %s", attempt + 1, MAX_RETRIES, e)
            if attempt == MAX_RETRIES - 1:
                return None
            time.sleep(RETRY_BASE_DELAY * (2 ** attempt))

    return None


def parse_csv(content: str) -> Optional[dict]:
    """Parse the EPU Daily CSV content.

    CSV format:
        day,month,year,daily_policy_index
        1,1,1985,103.83
        2,1,1985,296.43
        ...

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
        day = row.get("day", "").strip()
        month = row.get("month", "").strip()
        year = row.get("year", "").strip()
        value_raw = row.get("daily_policy_index", "").strip()

        if not (day and month and year):
            continue

        date_str = f"{year}-{int(month):02d}-{int(day):02d}"

        value = None
        if value_raw:
            try:
                value = float(value_raw)
            except ValueError:
                pass

        rows.append({"date": date_str, "value": value})

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
        "series_id": "EPU_DAILY",
        "series_name": "US Daily Economic Policy Uncertainty Index",
        "source": "policyuncertainty.com (Baker, Bloom & Davis)",
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

    logger.info("EPU Daily parsed: latest=%s value=%.2f, total=%d rows",
                latest["date"], latest["value"], len(valid_rows))
    return result


def scrape_epu() -> Optional[dict]:
    """Scrape the latest EPU Daily Index data.

    Returns:
        Dict with parsed data, or None on failure.
    """
    logger.info("Fetching EPU Daily data from policyuncertainty.com")

    csv_content = fetch_csv()
    if not csv_content:
        logger.error("No CSV content retrieved")
        return None

    data = parse_csv(csv_content)
    if data is None:
        logger.error("Failed to parse EPU data")
        return None

    data["scraped_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime())

    logger.info("EPU data extracted: latest=%s value=%.2f",
                data.get("latest_date"), data.get("latest_value"))
    return data