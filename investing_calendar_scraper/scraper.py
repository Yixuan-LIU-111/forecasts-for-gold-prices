"""Scraper for Investing.com economic calendar widget."""

import logging
from typing import Optional

import cloudscraper

from config import (
    CALENDAR_IFRAME_URL,
    REQUEST_HEADERS,
    REQUEST_TIMEOUT,
    MAX_RETRIES,
    RETRY_BASE_DELAY,
)
from utils import retry_with_backoff


logger = logging.getLogger("investing_calendar_scraper")


def fetch_calendar_html() -> Optional[str]:
    """Fetch the economic calendar iframe HTML.

    Returns:
        Raw HTML string on success, ``None`` on failure.
    """
    scraper = cloudscraper.create_scraper()

    def _request():
        logger.info("Fetching calendar from %s", CALENDAR_IFRAME_URL.split("?")[0])
        resp = scraper.get(
            CALENDAR_IFRAME_URL,
            headers=REQUEST_HEADERS,
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        text = resp.text
        if len(text) < 1000 or "Just a moment" in text:
            raise RuntimeError("Blocked by Cloudflare or empty response")
        return text

    try:
        return retry_with_backoff(
            _request,
            max_retries=MAX_RETRIES,
            base_delay=RETRY_BASE_DELAY,
            logger=logger,
        )
    except Exception as exc:
        logger.error("Failed to fetch calendar after %s retries: %s", MAX_RETRIES, exc)
        return None
