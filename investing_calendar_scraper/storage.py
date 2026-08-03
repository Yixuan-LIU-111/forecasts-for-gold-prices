"""Persistence layer for Investing.com calendar data."""

import csv
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from config import OUTPUT_DIR, OUTPUT_FILE, HISTORY_FILE, CSV_FILE


logger = logging.getLogger("investing_calendar_scraper")


def _ensure_dir(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def save_snapshot(events: List[Dict[str, Any]], metadata: Optional[Dict[str, Any]] = None) -> bool:
    """Save the latest calendar snapshot as JSON and CSV.

    Args:
        events: Filtered list of calendar events.
        metadata: Optional extra metadata to include in the JSON output.

    Returns:
        True if both files were written successfully.
    """
    try:
        _ensure_dir(OUTPUT_FILE)
        _ensure_dir(CSV_FILE)

        snapshot = {
            "scraped_at": datetime.now().isoformat(),
            "week": metadata.get("week") if metadata else None,
            "event_count": len(events),
            "filters": metadata.get("filters") if metadata else {},
            "events": events,
        }

        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            json.dump(snapshot, f, ensure_ascii=False, indent=2)
        logger.info("Saved JSON snapshot to %s", OUTPUT_FILE)

        # CSV with Chinese-friendly headers
        csv_headers = ["日期", "时间", "货币", "活动", "重要性", "今值", "预测值", "前值"]
        with open(CSV_FILE, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(csv_headers)
            for e in events:
                writer.writerow([
                    e.get("date", ""),
                    e.get("time", ""),
                    e.get("currency", ""),
                    e.get("event", ""),
                    e.get("importance", ""),
                    e.get("actual", ""),
                    e.get("forecast", ""),
                    e.get("previous", ""),
                ])
        logger.info("Saved CSV snapshot to %s", CSV_FILE)

        return True
    except Exception as exc:
        logger.error("Failed to save snapshot: %s", exc)
        return False


def append_history(events: List[Dict[str, Any]]) -> bool:
    """Append a compact JSONL record to the history file.

    Args:
        events: Filtered list of calendar events.

    Returns:
        True if the record was appended successfully.
    """
    try:
        _ensure_dir(HISTORY_FILE)
        record = {
            "scraped_at": datetime.now().isoformat(),
            "event_count": len(events),
            "events": events,
        }
        with open(HISTORY_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
        logger.info("Appended history record to %s", HISTORY_FILE)
        return True
    except Exception as exc:
        logger.error("Failed to append history: %s", exc)
        return False
