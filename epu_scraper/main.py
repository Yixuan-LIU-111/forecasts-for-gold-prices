"""Main entry point for EPU Daily Index scraper.

Usage:
    python3 main.py              # Scrape and save
    python3 main.py --dry-run    # Scrape and print without saving
    python3 main.py --show-last  # Show last saved data
"""

import argparse
import sys
from datetime import datetime

from scraper import scrape_epu
from storage import save_data, load_latest
from utils import setup_logging


def print_data(data: dict):
    """Pretty-print the scraped EPU data."""
    print("\n=== US Daily Economic Policy Uncertainty Index (EPU) ===\n")
    print(f"  Latest Date:      {data.get('latest_date', 'N/A')}")
    print(f"  Latest Value:     {data.get('latest_value', 'N/A'):.2f}")
    print(f"  Total Obs:        {data.get('total_observations', 'N/A')}")
    print(f"  Valid Obs:        {data.get('valid_observations', 'N/A')}")

    date_range = data.get("date_range", {})
    if date_range:
        print(f"  Date Range:       {date_range.get('start')} to {date_range.get('end')}")

    stats = data.get("stats", {})
    if stats:
        print(f"  Min:              {stats.get('min', 'N/A'):.2f}")
        print(f"  Max:              {stats.get('max', 'N/A'):.2f}")
        print(f"  Mean:             {stats.get('mean', 'N/A'):.2f}")

    print(f"  Source:           {data.get('source', 'N/A')}")
    print(f"  Scraped At:       {data.get('scraped_at', 'N/A')}")

    recent = data.get("recent_data", [])
    if recent:
        print(f"\n  Recent 30 data points:")
        print(f"  {'Date':<14} {'Value':>8}")
        print(f"  {'-'*14} {'-'*8}")
        for r in recent[-10:]:
            val_str = f"{r['value']:.2f}" if r['value'] is not None else "N/A"
            print(f"  {r['date']:<14} {val_str:>8}")

    print()


def main():
    parser = argparse.ArgumentParser(
        description="EPU Daily Index Scraper from policyuncertainty.com"
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--dry-run", action="store_true",
                       help="Scrape and print only, don't save")
    group.add_argument("--show-last", action="store_true",
                       help="Show last saved data")
    args = parser.parse_args()

    setup_logging()

    if args.show_last:
        data = load_latest()
        if data:
            print_data(data)
        else:
            print("No saved EPU data found.")
            sys.exit(1)
        return

    # Scrape
    data = scrape_epu()
    if data is None:
        print("Failed to scrape EPU data.")
        sys.exit(1)

    print_data(data)

    if not args.dry_run:
        saved = save_data(data)
        if saved:
            print(f"Data saved to {saved}")
        else:
            print("Warning: Data may not have been saved successfully.")
    else:
        print("(dry-run mode, data not saved)")


if __name__ == "__main__":
    main()