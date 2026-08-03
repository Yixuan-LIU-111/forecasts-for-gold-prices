"""Main entry point for GPR (Geopolitical Risk Index) scraper.

Usage:
    python3 main.py             # Scrape and save
    python3 main.py --dry-run   # Scrape and print without saving
    python3 main.py --show-last # Show last saved data
"""

import argparse
import sys

from scraper import scrape_gpr
from storage import save_data, load_latest
from utils import setup_logging


def print_data(data: dict):
    """Pretty-print the scraped GPR data."""
    print("\n=== Geopolitical Risk Index (GPR) ===\n")
    print(f"  Date:              {data.get('date', 'N/A')}")
    print(f"  GPRD (Daily GPR):  {data.get('gprd', 'N/A'):.2f}")
    print(f"  GPRD_ACT (Acts):   {data.get('gprd_act', 'N/A'):.2f}")
    print(f"  GPRD_THREAT:       {data.get('gprd_threat', 'N/A'):.2f}")
    print(f"  GPRD_MA7 (7-day):  {data.get('gprd_ma7', 'N/A'):.2f}")
    print(f"  GPRD_MA30 (30-day):{data.get('gprd_ma30', 'N/A'):.2f}")
    print(f"  N10D (Articles):   {data.get('n10d', 'N/A')}")
    if data.get("prev_gprd"):
        print(f"  Prev Day GPRD:     {data['prev_gprd']:.2f}")
    print(f"  Source:            {data.get('source', 'N/A')}")
    print(f"  Scraped At:        {data.get('scraped_at', 'N/A')}")
    print()


def main():
    parser = argparse.ArgumentParser(
        description="GPR (Geopolitical Risk Index) Scraper"
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
            print("No saved GPR data found.")
            sys.exit(1)
        return

    # Scrape
    data = scrape_gpr()
    if data is None:
        print("Failed to scrape GPR data.")
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