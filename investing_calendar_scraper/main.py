#!/usr/bin/env python3
"""Investing.com Economic Calendar Scraper - Entry Point.

Extracts high-importance economic events for the current week from
Investing.com's calendar widget and persists them as JSON/CSV.

Usage:
    python main.py                     # Scrape and save
    python main.py --dry-run           # Print data without saving
    python main.py --verbose           # Enable debug logging
"""

import argparse
import sys

from config import LOG_FILE, LOG_LEVEL, TARGET_CATEGORIES, TARGET_IMPORTANCE
from parser import filter_events, get_week_bounds, parse_calendar
from scraper import fetch_calendar_html
from storage import append_history, save_snapshot
from utils import setup_logger


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Scrape high-importance economic calendar events from Investing.com",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print scraped data to console without saving to disk",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable debug logging",
    )
    return parser.parse_args()


def print_events(events: list) -> None:
    """Pretty-print events to the console."""
    if not events:
        print("No matching events found.")
        return

    print(f"\n=== Economic Calendar Events ({len(events)} found) ===\n")
    print(f"{'Date':<12} {'Time':<8} {'Currency':<8} {'Event':<45} {'Actual':<12} {'Forecast':<12} {'Previous':<12}")
    print("-" * 120)
    for e in events:
        print(
            f"{e['date']:<12} {e['time']:<8} {e['currency']:<8} "
            f"{e['event']:<45} {e['actual']:<12} {e['forecast']:<12} {e['previous']:<12}"
        )
    print()


def main() -> int:
    args = parse_args()
    level = "DEBUG" if args.verbose else LOG_LEVEL
    logger = setup_logger("investing_calendar_scraper", log_file=LOG_FILE, level=level)

    logger.info("Starting Investing.com economic calendar scraper")

    html = fetch_calendar_html()
    if html is None:
        logger.error("Failed to fetch calendar HTML")
        return 1

    all_events = parse_calendar(html)
    logger.info("Parsed %s total events", len(all_events))

    filtered = filter_events(all_events)
    logger.info(
        "Filtered to %s %s-importance events in categories %s",
        len(filtered),
        TARGET_IMPORTANCE,
        TARGET_CATEGORIES,
    )

    monday, sunday = get_week_bounds()

    if args.dry_run:
        print_events(filtered)
        return 0

    metadata = {
        "week": {"from": monday, "to": sunday},
        "filters": {
            "importance": TARGET_IMPORTANCE,
            "categories": TARGET_CATEGORIES,
        },
    }

    ok_snapshot = save_snapshot(filtered, metadata=metadata)
    ok_history = append_history(filtered)

    if ok_snapshot and ok_history:
        print_events(filtered)
        logger.info("Scraper finished successfully")
        return 0

    logger.error("Failed to persist data")
    return 1


if __name__ == "__main__":
    sys.exit(main())
