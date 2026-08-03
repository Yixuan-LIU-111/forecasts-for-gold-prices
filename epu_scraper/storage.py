"""Storage for EPU Daily Index scraped data."""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from config import OUTPUT_DIR, OUTPUT_FILE, HISTORY_FILE

logger = logging.getLogger(__name__)


def save_data(data: dict) -> Optional[Path]:
    """Save scraped EPU data to JSON files.

    Saves:
        1. Latest snapshot: epu_daily_latest.json (overwrite)
        2. Historical record: epu_daily_history.jsonl (append)

    Args:
        data: Scraped data dict.

    Returns:
        Path to the latest snapshot file, or None on failure.
    """
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    if "scraped_at" not in data:
        data["scraped_at"] = datetime.now(timezone.utc).isoformat()

    # Save latest snapshot
    try:
        with open(str(OUTPUT_FILE), "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
        logger.info("Latest EPU data saved to %s", OUTPUT_FILE)
    except Exception as e:
        logger.error("Failed to save latest EPU data: %s", e)
        return None

    # Append summary to history
    try:
        summary = {
            "latest_date": data.get("latest_date"),
            "latest_value": data.get("latest_value"),
            "total_observations": data.get("total_observations"),
            "scraped_at": data.get("scraped_at"),
            "_saved_at": datetime.now(timezone.utc).isoformat(),
        }
        with open(str(HISTORY_FILE), "a", encoding="utf-8") as f:
            f.write(json.dumps(summary, ensure_ascii=False) + "\n")
        logger.info("EPU data appended to history: %s", HISTORY_FILE)
    except Exception as e:
        logger.error("Failed to save EPU history: %s", e)

    return OUTPUT_FILE


def load_latest() -> Optional[dict]:
    """Load the latest saved EPU snapshot.

    Returns:
        Parsed dict, or None if no saved data exists.
    """
    if not OUTPUT_FILE.exists():
        return None
    try:
        with open(str(OUTPUT_FILE), "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error("Failed to load latest EPU data: %s", e)
        return None