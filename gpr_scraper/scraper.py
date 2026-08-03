"""Scrape GPR (Geopolitical Risk Index) data from Matteo Iacoviello's website.

Data source: https://www.matteoiacoviello.com/gpr.htm
Excel file: data_gpr_daily_recent.xls
"""

import logging
import time
from typing import Optional

import requests

from config import (
    GPR_EXCEL_URL,
    REQUEST_HEADERS,
    MIN_DELAY_SECONDS,
    MAX_RETRIES,
    RETRY_BASE_DELAY,
    REQUEST_TIMEOUT,
)
from parser import parse_gpr_excel

logger = logging.getLogger(__name__)


def download_excel() -> Optional[bytes]:
    """Download the GPR daily data Excel file with retry logic.

    Returns:
        Raw bytes of the .xls file, or None on failure.
    """
    for attempt in range(MAX_RETRIES):
        try:
            time.sleep(RETRY_BASE_DELAY if attempt > 0 else MIN_DELAY_SECONDS)
            resp = requests.get(
                GPR_EXCEL_URL,
                headers=REQUEST_HEADERS,
                timeout=REQUEST_TIMEOUT,
            )
            resp.raise_for_status()
            logger.info("Excel file downloaded: %d bytes", len(resp.content))
            return resp.content
        except requests.exceptions.Timeout:
            logger.warning("Attempt %d/%d timed out", attempt + 1, MAX_RETRIES)
            if attempt == MAX_RETRIES - 1:
                logger.error("Failed to download Excel after %d attempts", MAX_RETRIES)
                return None
            time.sleep(RETRY_BASE_DELAY * (2 ** attempt))
        except requests.exceptions.RequestException as e:
            logger.warning("Attempt %d/%d failed: %s", attempt + 1, MAX_RETRIES, e)
            if attempt == MAX_RETRIES - 1:
                logger.error("Failed to download Excel after %d attempts", MAX_RETRIES)
                return None
            time.sleep(RETRY_BASE_DELAY * (2 ** attempt))


def scrape_gpr() -> Optional[dict]:
    """Scrape the latest GPR data from the Excel file.

    Returns:
        Dict with parsed GPR data, or None on failure.
    """
    logger.info("Downloading GPR data from %s", GPR_EXCEL_URL)

    content = download_excel()
    if not content:
        logger.error("No Excel content retrieved")
        return None

    data = parse_gpr_excel(content)
    if data is None:
        logger.error("Failed to parse GPR data from Excel")
        return None

    data["scraped_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime())

    logger.info("GPR data extracted: date=%s, gprd=%.2f",
                data.get("date"), data.get("gprd"))
    return data