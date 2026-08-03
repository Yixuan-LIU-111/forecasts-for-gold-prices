"""Scrape DXY (Dollar Index) data from Sina Finance using Playwright."""

import time
import logging
from typing import Optional

from playwright.sync_api import sync_playwright

from config import (
    SINA_DXY_URL,
    REQUEST_HEADERS,
    MIN_DELAY_SECONDS,
    MAX_RETRIES,
    RETRY_BASE_DELAY,
    PLAYWRIGHT_TIMEOUT_MS,
    PLAYWRIGHT_WAIT_MS,
)
from parser import parse_dxy_data

logger = logging.getLogger(__name__)


def fetch_page_playwright(url: str, wait_ms: int = PLAYWRIGHT_WAIT_MS) -> Optional[str]:
    """Fetch page content using Playwright with retry logic.

    Args:
        url: Target URL.
        wait_ms: Milliseconds to wait after page load for JS rendering.

    Returns:
        Page body text, or None if failed.
    """
    for attempt in range(MAX_RETRIES):
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                context = browser.new_context(
                    viewport={"width": 414, "height": 896},
                    user_agent=REQUEST_HEADERS["User-Agent"],
                )
                page = context.new_page()
                page.goto(url, wait_until="domcontentloaded", timeout=PLAYWRIGHT_TIMEOUT_MS)
                page.wait_for_timeout(wait_ms)

                # Wait for the price data to appear
                try:
                    page.wait_for_selector(".sft-header-symbol", timeout=10000)
                except Exception:
                    logger.debug("sft-header-symbol not found quickly, continuing anyway")

                body_text = page.evaluate("() => document.body.innerText")
                browser.close()
                return body_text
        except Exception as e:
            logger.warning("Attempt %d/%d failed: %s", attempt + 1, MAX_RETRIES, e)
            if attempt == MAX_RETRIES - 1:
                logger.error("Failed to fetch %s after %d attempts", url, MAX_RETRIES)
                return None
            time.sleep(RETRY_BASE_DELAY * (2 ** attempt))


def scrape_dxy() -> Optional[dict]:
    """Scrape the latest DXY data from Sina Finance.

    Returns:
        Dict with parsed DXY data, or None on failure.
    """
    logger.info("Fetching DXY data from %s", SINA_DXY_URL)

    time.sleep(MIN_DELAY_SECONDS)  # Rate limiting

    body_text = fetch_page_playwright(SINA_DXY_URL)
    if not body_text:
        logger.error("No page content retrieved")
        return None

    # Try structured parsing first
    data = parse_dxy_data(body_text)
    if data is None:
        logger.error("Failed to parse DXY data from page content")
        return None

    # Add metadata
    data["scraped_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime())

    logger.info("DXY data extracted: current_price=%.4f, prev_close=%.4f",
                data.get("current_price"), data.get("prev_close"))
    return data