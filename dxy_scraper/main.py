"""Main entry point for DXY (Dollar Index) scraper from Sina Finance.

Usage:
    python3 main.py             # Scrape and save
    python3 main.py --dry-run   # Scrape and print without saving
    python3 main.py --show-last # Show last saved data
"""

import argparse
import sys
from datetime import datetime

from scraper import scrape_dxy
from storage import save_data, load_latest
from utils import setup_logging


def print_data(data: dict):
    """Pretty-print the scraped DXY data."""
    print("\n=== 美元指数 (DXY) Data ===\n")
    print(f"  Current Price:  {data.get('current_price', 'N/A')}")
    print(f"  Change:         {data.get('change_percent', 'N/A')}  ({data.get('change_amount', 'N/A')})")
    print(f"  Prev Close:     {data.get('prev_close', 'N/A')}")
    print(f"  Open:           {data.get('open', 'N/A')}")
    print(f"  High:           {data.get('high', 'N/A')}")
    print(f"  Low:            {data.get('low', 'N/A')}")
    print(f"  Date:           {data.get('date', 'N/A')}")
    print(f"  Time:           {data.get('time', 'N/A')}")
    print(f"  Scraped At:     {data.get('scraped_at', 'N/A')}")
    print()


def main():
    parser = argparse.ArgumentParser(description="DXY (Dollar Index) Scraper from Sina Finance")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--dry-run", action="store_true", help="Scrape and print only, don't save")
    group.add_argument("--show-last", action="store_true", help="Show last saved data")
    args = parser.parse_args()

    setup_logging()

    if args.show_last:
        data = load_latest()
        if data:
            print_data(data)
        else:
            print("No saved DXY data found.")
            sys.exit(1)
        return

    # Scrape
    data = scrape_dxy()
    if data is None:
        print("Failed to scrape DXY data.")
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