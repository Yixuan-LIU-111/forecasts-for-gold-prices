"""Persist VIX data to JSON storage."""

import logging
from typing import Optional

from config import OUTPUT_FILE, HISTORY_FILE
from utils import ensure_dir, save_json, append_jsonl, now_utc, load_json

logger = logging.getLogger(__name__)


def save_vix_snapshot(data: dict) -> bool:
    """Save the latest VIX snapshot to JSON and append to history.

    This function:
    1. Appends the data point to a JSONL history file (for time series).
    2. Overwrites the latest snapshot JSON file.

    Args:
        data: VIX data dict to persist.

    Returns:
        True if all writes succeeded, False otherwise.
    """
    ensure_dir(OUTPUT_FILE.parent)
    ensure_dir(HISTORY_FILE.parent)

    # Add scraped_at timestamp
    record = {
        "scraped_at": now_utc(),
        **data,
    }

    success = True

    # 1. Append to JSONL history (one JSON object per line)
    if not append_jsonl(record, HISTORY_FILE):
        logger.error("Failed to append to history file: %s", HISTORY_FILE)
        success = False
    else:
        logger.info("Appended record to history: %s", HISTORY_FILE)

    # 2. Overwrite latest snapshot JSON
    if not save_json(record, OUTPUT_FILE):
        logger.error("Failed to save latest snapshot: %s", OUTPUT_FILE)
        success = False
    else:
        logger.info("Saved latest snapshot: %s", OUTPUT_FILE)

    return success


def load_latest_snapshot() -> Optional[dict]:
    """Load the most recent VIX snapshot from disk."""
    return load_json(OUTPUT_FILE)