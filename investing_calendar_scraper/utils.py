"""Utility helpers for the Investing.com calendar scraper."""

import logging
import sys
import time
from typing import Optional


def setup_logger(name: str, log_file, level: str = "INFO") -> logging.Logger:
    """Configure a logger writing to both console and file."""
    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, level.upper()))
    logger.handlers = []

    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(formatter)
    logger.addHandler(console)

    try:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(log_file, encoding="utf-8")
        fh.setFormatter(formatter)
        logger.addHandler(fh)
    except Exception as exc:
        logger.warning("Could not create file handler: %s", exc)

    return logger


def retry_with_backoff(
    func,
    max_retries: int = 3,
    base_delay: float = 2.0,
    logger: Optional[logging.Logger] = None,
):
    """Execute ``func`` and retry on failure with exponential backoff."""
    last_exc = None
    for attempt in range(1, max_retries + 1):
        try:
            time.sleep(0.5)  # polite delay before each attempt
            return func()
        except Exception as exc:
            last_exc = exc
            if logger:
                logger.warning("Attempt %s failed: %s", attempt, exc)
            if attempt < max_retries:
                sleep_time = base_delay * (2 ** (attempt - 1))
                if logger:
                    logger.info("Retrying in %.1f seconds...", sleep_time)
                time.sleep(sleep_time)
    raise last_exc
