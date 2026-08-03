"""Scrape VIX data from CBOE website using Playwright.

Optimized strategy (based on page structure analysis):
  1. "Trade Data" section → h2 elements for spot price ($), change (%),
     and date (as of ...)
  2. "Market Data" section → prev close, open, 52-week range
  3. RSC payload parsing as fallback only
"""

import logging
import re
import time
from typing import Optional

from playwright.sync_api import TimeoutError as PlaywrightTimeout, sync_playwright

from config import (
    CBOE_VIX_URL,
    PLAYWRIGHT_TIMEOUT_MS,
    PLAYWRIGHT_WAIT_MS,
    REQUEST_HEADERS,
    MAX_RETRIES,
    MIN_DELAY_SECONDS,
    CBOE_VIX_DASHBOARD_URL,
)
from parser import parse_vix_data

logger = logging.getLogger(__name__)


def _get_trade_data_section(page):
    """Locate the 'Trade Data' section and return the parent element.

    'Trade Data' is an <h1> element inside a <section>.
    """
    try:
        trade_h1 = page.locator("h1:has-text('Trade Data')").first
        if trade_h1.count() > 0:
            return trade_h1.locator("xpath=ancestor::section").first
    except Exception:
        pass
    return None


def _get_market_data_section(page):
    """Locate the 'Market Data' section and return the parent element.

    'Market Data' is an <h1> element inside a <section>.
    """
    try:
        md_h1 = page.locator("h1:has-text('Market Data')").first
        if md_h1.count() > 0:
            return md_h1.locator("xpath=ancestor::section").first
    except Exception:
        pass
    return None


def _extract_spot_price_and_change(section) -> Optional[dict]:
    """Extract VIX spot price, change, and date from h2 elements in a section.

    Inside the Trade Data section, the first three h2 elements are:
      h2[0]: "(as of July 28, 2026)"   ← date
      h2[1]: "$19.06"                   ← spot price
      h2[2]: "2.09% (0.39)"             ← change percent (amount)
    """
    result = {}
    try:
        h2s = section.locator("h2").all()
        for h2 in h2s:
            try:
                text = h2.inner_text().strip()
            except Exception:
                continue

            # Date: "(as of ...)"
            m = re.match(r"\(as of (.+?)\)", text)
            if m:
                result["data_as_of"] = m.group(1).strip()
                continue

            # Spot price: "$19.06"
            m = re.match(r"\$([\d.]+)", text)
            if m:
                result["vix_spot_price"] = float(m.group(1))
                continue

            # Change: "2.09% (0.39)" or "-0.50% (-0.10)"
            m = re.match(r"([+-]?[\d.]+%)\s*\(([\d.]+)\)", text)
            if m:
                result["change_percent_display"] = m.group(1)
                result["change_amount"] = float(m.group(2))
                pct_num = re.sub(r"[%+]", "", m.group(1))
                try:
                    result["change_percent"] = round(float(pct_num), 2)
                except ValueError:
                    pass
                continue
    except Exception as e:
        logger.warning("Error extracting spot price: %s", e)

    return result if result.get("vix_spot_price") else None


def _extract_market_data(section) -> Optional[dict]:
    """Extract market data details from the Market Data section.

    The section contains text like:
      PREV. CLOSE  18.67
      OPEN  17.62
      CHANGE  +2.09%
      52 WEEK  35.30  HIGH  13.38  LOW
    """
    result = {}
    try:
        section_text = section.inner_text()
    except Exception:
        return None

    # Prev close
    m = re.search(r"PREV\.\s*CLOSE\s*([\d.]+)", section_text)
    if m:
        result["prev_close"] = float(m.group(1))

    # Open
    m = re.search(r"OPEN\s*([\d.]+)", section_text)
    if m:
        result["open"] = float(m.group(1))

    # Change
    m = re.search(r"CHANGE\s*([+-]?[\d.]+%)", section_text)
    if m:
        result["change_pct_market"] = m.group(1)

    # 52-week range
    m = re.search(r"52\s*WEEK\s*([\d.]+)\s*HIGH\s*([\d.]+)\s*LOW", section_text)
    if m:
        result["high_52w"] = float(m.group(1))
        result["low_52w"] = float(m.group(2))

    # Intraday range from table data
    # Look for "Intraday" or the chart data
    numbers = re.findall(r"([\d.]+)\s*\n\s*([\d.]+)\s*\n\s*([\d.]+)", section_text)
    if numbers:
        # The chart data shows a sequence of prices
        all_vals = [float(n) for group in numbers for n in group]
        if all_vals:
            result["low_today"] = round(min(all_vals), 2)
            result["high_today"] = round(max(all_vals), 2)

    return result if result else None


class VIXScraper:
    """Scraper for CBOE VIX index data using Playwright."""

    def __init__(self, headless: bool = True):
        self.headless = headless
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def _start_browser(self):
        """Launch Playwright browser and create a new context."""
        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(
            headless=self.headless,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
            ],
        )
        self._context = self._browser.new_context(
            user_agent=REQUEST_HEADERS["User-Agent"],
            viewport={"width": 1920, "height": 1080},
            locale="en-US",
        )
        self._page = self._context.new_page()

    def close(self):
        """Release all browser resources."""
        try:
            if self._page:
                self._page.close()
            if self._context:
                self._context.close()
            if self._browser:
                self._browser.close()
            if self._playwright:
                self._playwright.stop()
        except Exception as e:
            logger.warning("Error while closing browser: %s", e)
        finally:
            self._page = None
            self._context = None
            self._browser = None
            self._playwright = None

    def fetch_vix_data(self, url: str = CBOE_VIX_URL) -> Optional[dict]:
        """Fetch VIX data from CBOE page with retry logic.

        Strategy:
          1. Extract from "Trade Data" section DOM (h2 elements)
          2. Extract from "Market Data" section for details
          3. Fallback to RSC payload parsing

        Args:
            url: CBOE page URL to scrape.

        Returns:
            Parsed VIX data dict, or None on failure.
        """
        urls_to_try = [url, CBOE_VIX_DASHBOARD_URL]
        last_error = None

        for current_url in urls_to_try:
            for attempt in range(1, MAX_RETRIES + 1):
                logger.info(
                    "Attempt %d/%d: Fetching %s", attempt, MAX_RETRIES, current_url
                )
                try:
                    self._start_browser()
                    self._page.goto(
                        current_url,
                        wait_until="domcontentloaded",
                        timeout=PLAYWRIGHT_TIMEOUT_MS,
                    )

                    # Wait for key content to appear
                    try:
                        self._page.wait_for_selector(
                            "text=VIX",
                            timeout=PLAYWRIGHT_WAIT_MS,
                        )
                    except PlaywrightTimeout:
                        logger.warning(
                            "VIX text not found quickly, continuing anyway"
                        )

                    # Give time for dynamic rendering
                    self._page.wait_for_timeout(3000)

                    # --- Strategy 1: DOM-based extraction from Trade Data section ---
                    trade_section = _get_trade_data_section(self._page)
                    extracted = None
                    if trade_section is not None and trade_section.count() > 0:
                        extracted = _extract_spot_price_and_change(trade_section)
                        if extracted:
                            logger.info(
                                "DOM extraction successful: $%.2f",
                                extracted.get("vix_spot_price", 0),
                            )

                    # --- Strategy 2: Market Data section for details ---
                    market_data = None
                    md_section = _get_market_data_section(self._page)
                    if md_section is not None and md_section.count() > 0:
                        market_data = _extract_market_data(md_section)
                        if market_data:
                            logger.info(
                                "Market data extracted: prev_close=%s",
                                market_data.get("prev_close", "N/A"),
                            )

                    # --- Fallback: RSC payload parsing ---
                    html = self._page.content()
                    parsed = parse_vix_data(html) if html else None

                    # Merge: DOM data takes priority, RSC data fills gaps
                    result = {}
                    if extracted:
                        result.update(extracted)
                    if market_data:
                        # Merge market data, don't overwrite DOM values
                        for k, v in market_data.items():
                            if k not in result:
                                result[k] = v
                    if parsed:
                        # Fill in any missing fields from RSC data
                        for k, v in parsed.items():
                            if k not in result:
                                result[k] = v

                    if result.get("vix_spot_price") is not None:
                        logger.info(
                            "Successfully parsed VIX data: spot=%.2f",
                            result["vix_spot_price"],
                        )
                        self.close()
                        return result
                    else:
                        logger.warning(
                            "No VIX spot price found from any extraction method"
                        )
                        self.close()
                        last_error = "No VIX data found"

                except PlaywrightTimeout:
                    logger.warning(
                        "Timeout on attempt %d for %s", attempt, current_url
                    )
                    last_error = "Page load timeout"
                except Exception as e:
                    logger.warning(
                        "Error on attempt %d for %s: %s", attempt, current_url, e
                    )
                    last_error = str(e)
                finally:
                    self.close()

                if attempt < MAX_RETRIES:
                    delay = MIN_DELAY_SECONDS * (2 ** (attempt - 1))
                    logger.info("Waiting %.1f seconds before retry...", delay)
                    time.sleep(delay)

        logger.error("All attempts failed for VIX. Last error: %s", last_error)
        return None