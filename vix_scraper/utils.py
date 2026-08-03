"""Utility functions for VIX scraper."""

import json
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


def setup_logger(
    name: str,
    log_file: Optional[Path] = None,
    level: str = "INFO",
) -> logging.Logger:
    """Configure and return a logger with console and optional file output."""
    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    if not logger.handlers:
        console = logging.StreamHandler(sys.stdout)
        console.setFormatter(formatter)
        logger.addHandler(console)

        if log_file:
            log_file.parent.mkdir(parents=True, exist_ok=True)
            fh = logging.FileHandler(log_file, encoding="utf-8")
            fh.setFormatter(formatter)
            logger.addHandler(fh)

    return logger


def now_utc() -> str:
    """Return current UTC timestamp as ISO 8601 string."""
    return datetime.now(timezone.utc).isoformat()


def ensure_dir(path: Path) -> Path:
    """Ensure directory exists and return the path."""
    path.mkdir(parents=True, exist_ok=True)
    return path


def load_json(filepath: Path) -> Optional[dict]:
    """Load JSON file if it exists, otherwise return None."""
    if filepath.exists() and filepath.stat().st_size > 0:
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            logging.getLogger(__name__).warning("Failed to load %s: %s", filepath, e)
    return None


def save_json(data: dict, filepath: Path) -> bool:
    """Save data as formatted JSON. Returns True on success."""
    try:
        filepath.parent.mkdir(parents=True, exist_ok=True)
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return True
    except OSError as e:
        logging.getLogger(__name__).error("Failed to save %s: %s", filepath, e)
        return False


def append_jsonl(data: dict, filepath: Path) -> bool:
    """Append a JSON line to a JSONL file. Returns True on success."""
    try:
        filepath.parent.mkdir(parents=True, exist_ok=True)
        with open(filepath, "a", encoding="utf-8") as f:
            f.write(json.dumps(data, ensure_ascii=False) + "\n")
        return True
    except OSError as e:
        logging.getLogger(__name__).error("Failed to append %s: %s", filepath, e)
        return False


def wait_with_backoff(attempt: int, base_delay: float = 2.0) -> None:
        """Sleep with exponential backoff."""
        delay = base_delay * (2 ** (attempt - 1))
        logging.getLogger(__name__).debug("Waiting %.1f seconds before retry...", delay)
        time.sleep(delay)