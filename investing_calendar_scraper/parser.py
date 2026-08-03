"""HTML parser and filter logic for Investing.com economic calendar."""

import re
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from bs4 import BeautifulSoup

from config import TARGET_IMPORTANCE, TARGET_CATEGORIES


# Keyword-based category classifier. Investing.com does not expose the
# category in the public widget HTML, so we classify events locally by name.
# These keywords map to the four filter categories requested:
#   就业 (Employment), 通货膨胀 (Inflation), 经济活动 (Economic Activity), 央行 (Central Banks)
CATEGORY_KEYWORDS: Dict[str, List[str]] = {
    "employment": [
        "employment", "unemployment", "jobless", "payroll", "nonfarm", "nfp",
        "labor", "wages", "claim", "jolts", "adp", "participation",
    ],
    "inflation": [
        "cpi", "pce", "ppi", "inflation", "price index", "wpi", "deflator",
        "consumer prices", "producer prices", "prices",
    ],
    "economic_activity": [
        "gdp", "industrial production", "manufacturing", "services pmi", "pmi",
        "retail sales", "durable goods", "trade balance", "current account",
        "business climate", "ifo", "factory orders", "construction",
        "housing starts", "building permits", "new home sales", "existing home sales",
        "wholesale inventories", "business inventories", "capacity utilization",
        "factory output", "leading index", "composite pmi", "chicago pmi",
        "empire state", "philadelphia fed", "dallas fed", "richmond fed", "kc fed",
        "industrial profit",
    ],
    "central_banks": [
        "interest rate", "fomc", "fed", "boe", "boj", "ecb", "monetary policy",
        "rate decision", "rate statement", "press conference", "speaks", "speech",
        "minutes", "bank of", "central bank", "federal reserve", "governor", "president",
    ],
}

CATEGORY_LABELS: Dict[str, str] = {
    "employment": "就业",
    "inflation": "通货膨胀",
    "economic_activity": "经济活动",
    "central_banks": "央行",
}


def _classify_event(event_name: str) -> List[str]:
    """Return category keys matching ``event_name`` based on keywords."""
    name_lower = event_name.lower()
    matched = []
    for category, keywords in CATEGORY_KEYWORDS.items():
        if any(kw in name_lower for kw in keywords):
            matched.append(category)
    return matched


def _importance_from_title(title: str) -> str:
    """Map the sentiment cell title to a human-readable importance string."""
    if "High Volatility" in title:
        return "High"
    if "Moderate Volatility" in title:
        return "Medium"
    if "Low Volatility" in title:
        return "Low"
    return ""


def _parse_date(date_text: str) -> Optional[str]:
    """Convert a date header like 'Monday, July 27, 2026' to '2026-07-27'."""
    try:
        # Remove weekday prefix
        cleaned = re.sub(r"^[A-Za-z]+,\s*", "", date_text.strip())
        dt = datetime.strptime(cleaned, "%B %d, %Y")
        return dt.strftime("%Y-%m-%d")
    except ValueError:
        return None


def get_week_bounds() -> tuple:
    """Return (monday, sunday) for the current week as date strings."""
    today = datetime.now()
    monday = today - timedelta(days=today.weekday())
    sunday = monday + timedelta(days=6)
    return monday.strftime("%Y-%m-%d"), sunday.strftime("%Y-%m-%d")


def parse_calendar(html: str) -> List[Dict[str, Any]]:
    """Parse all events from the calendar HTML table.

    Args:
        html: Raw HTML from the Investing.com calendar widget.

    Returns:
        List of event dictionaries with keys:
        date, time, currency, event, importance, actual, forecast, previous,
        categories (list), category_labels (list).
    """
    soup = BeautifulSoup(html, "html.parser")
    rows = soup.find_all("tr")

    events: List[Dict[str, Any]] = []
    current_date_text = ""
    current_date_iso = ""

    for row in rows:
        cells = row.find_all(["td", "th"])

        # Date header row
        if len(cells) == 1 and cells[0].get("class") and "theDay" in cells[0].get("class", []):
            current_date_text = cells[0].get_text(strip=True)
            current_date_iso = _parse_date(current_date_text) or ""
            continue

        # Data row
        if len(cells) == 8:
            time_val = cells[0].get_text(strip=True)
            currency = cells[1].get_text(strip=True)
            importance = _importance_from_title(cells[2].get("title", ""))
            event_name = cells[3].get_text(strip=True)
            actual = cells[4].get_text(strip=True)
            forecast = cells[5].get_text(strip=True)
            previous = cells[6].get_text(strip=True)

            if not time_val or not event_name or time_val == "Time":
                continue

            categories = _classify_event(event_name)
            events.append({
                "date": current_date_iso,
                "date_display": current_date_text,
                "time": time_val,
                "currency": currency,
                "event": event_name,
                "importance": importance,
                "actual": actual,
                "forecast": forecast,
                "previous": previous,
                "categories": categories,
                "category_labels": [CATEGORY_LABELS[c] for c in categories],
            })

    return events


def filter_events(events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Filter events by target importance and categories.

    Args:
        events: Parsed event list.

    Returns:
        Events matching ``TARGET_IMPORTANCE`` and at least one of ``TARGET_CATEGORIES``.
    """
    target_set = set(TARGET_CATEGORIES)
    filtered = []
    for event in events:
        if event["importance"] != TARGET_IMPORTANCE:
            continue
        if not any(cat in target_set for cat in event["categories"]):
            continue
        filtered.append(event)
    return filtered
