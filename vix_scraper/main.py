#!/usr/bin/env python3
"""VIX Index Scraper - Entry Point.

Scrapes the latest VIX (CBOE Volatility Index) data from CBOE website
and persists it as JSON.

Usage:
    python main.py                     # Scrape and save
    python main.py --dry-run           # Print data without saving
    python main.py --help              # Show help
"""

import argparse
import sys

from config import LOG_DIR, LOG_FILE, LOG_LEVEL
from scraper import VIXScraper
from storage import save_vix_snapshot, load_latest_snapshot
from utils import setup_logger


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Scrape the latest VIX (CBOE Volatility Index) data",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print scraped data to console without saving to disk",
    )
    parser.add_argument(
        "--show-last",
        action="store_true",
        help="Show the most recently saved snapshot and exit",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable debug logging",
    )
    return parser.parse_args()


def show_last_snapshot():
    """Display the most recent saved snapshot."""
    data = load_latest_snapshot()
    if data:
        print("\n=== Latest Saved VIX Snapshot ===\n")
        for key, value in data.items():
            print(f"  {key}: {value}")
        print()
    else:
        print("No saved VIX snapshot found. Run without --show-last to scrape.")


def print_data(data: dict):
    """Pretty-print the scraped VIX data."""
    change_pct = data.get("change_percent_display") or f"{data.get('change_percent', 'N/A')}%"
    change_amt = data.get("change_amount", "N/A")
    print("\n=== VIX Index Data ===\n")
    print(f"  VIX Spot Price:  {data.get('vix_spot_price', 'N/A')}")
    print(f"  Change:          {change_pct}  ({change_amt})")
    print(f"  Previous Close:  {data.get('prev_close', 'N/A')}")
    print(f"  Open:            {data.get('open', 'N/A')}")
    print(f"  Day Range:       {data.get('low_today', 'N/A')} - {data.get('high_today', 'N/A')}")
    lo = data.get("low_52w")
    hi = data.get("high_52w")
    if lo and hi:
        print(f"  52-Week Range:   {lo} - {hi}")
    print(f"  Data As Of:      {data.get('data_as_of', 'N/A')}")
    print(f"  Scraped At:      {data.get('scraped_at', 'N/A')}")
    print()


def main():
    args = parse_args()
    level = "DEBUG" if args.verbose else LOG_LEVEL
    setup_logger("vix_scraper", log_file=LOG_FILE, level=level)

    if args.show_last:
        show_last_snapshot()
        return

    scraper = VIXScraper(headless=True)
    data = scraper.fetch_vix_data()

    if data is None:
        print("ERROR: Failed to scrape VIX data.", file=sys.stderr)
        sys.exit(1)

    if args.dry_run:
        print_data(data)
        return

    if save_vix_snapshot(data):
        print_data(data)
        print(f"Data saved to output files.")
    else:
        print("ERROR: Failed to persist VIX data.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()