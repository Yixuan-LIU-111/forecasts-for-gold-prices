"""Parse DXY (Dollar Index) data from Sina Finance page."""

import re
from datetime import datetime
from typing import Optional


def parse_dxy_data(page_text: str) -> Optional[dict]:
    """Extract DXY data from the Sina Finance page body text.

    The page body text has a fixed structure:
        Line 11: current price (e.g., "101.5438")
        Line 12: change amount (e.g., "+0.0146")
        Line 13: change percent (e.g., "+0.0144%")
        Line 14: date (e.g., "07-28")
        Line 15: time (e.g., "17:31:28")
        Lines 16-27: structured detail data (label, value, label, value, ...)

    Args:
        page_text: The full innerText of the page body.

    Returns:
        Parsed data dict, or None if parsing failed.
    """
    if not page_text:
        return None

    lines = [l.strip() for l in page_text.split('\n') if l.strip()]
    result = {}

    # Find the detail section starting from "今开"
    detail_start = None
    for i, line in enumerate(lines):
        if line == "今开" and i + 1 < len(lines):
            detail_start = i
            break

    if detail_start is None:
        # Fallback: use regex on the full text
        return _parse_with_regex(page_text)

    # Extract structured details
    details = {}
    i = detail_start
    while i + 1 < len(lines):
        label = lines[i]
        value = lines[i + 1]
        details[label] = value
        i += 2
        # Stop at common break points
        if label in ("波幅",) or "+自选" in value:
            break

    # Map Chinese labels to English keys
    label_map = {
        "今开": "open",
        "最高": "high",
        "振幅": "amplitude",
        "昨收": "prev_close",
        "最低": "low",
        "波幅": "volatility",
    }

    for cn_label, en_key in label_map.items():
        if cn_label in details:
            raw = details[cn_label].replace("%", "")
            try:
                result[en_key] = float(raw)
            except ValueError:
                result[en_key] = raw

    # Current price (first numeric line before detail section)
    for i in range(detail_start - 1, -1, -1):
        if re.match(r'^[\d.]+$', lines[i]):
            try:
                result["current_price"] = float(lines[i])
                break
            except ValueError:
                pass

    # Change amount and percent
    for i in range(detail_start - 1, -1, -1):
        if re.match(r'^[+-]\d', lines[i]):
            val = lines[i]
            if '%' in val:
                result["change_percent"] = val
            elif re.match(r'^[+-][\d.]+$', val):
                try:
                    result["change_amount"] = float(val)
                except ValueError:
                    pass

    # Date and time
    for i in range(min(15, len(lines))):
        m = re.match(r'^(\d{2})-(\d{2})$', lines[i])
        if m:
            month, day = m.group(1), m.group(2)
            year = datetime.now().year
            result["date"] = f"{year}-{month}-{day}"
            # Look for time in the next few lines
            for j in range(i + 1, min(i + 3, len(lines))):
                tm = re.match(r'^(\d{2}:\d{2}:\d{2})$', lines[j])
                if tm:
                    result["time"] = tm.group(1)
                    break
            break

    # Series info
    result["series_name"] = "美元指数"
    result["series_id"] = "DINIW"

    return result if result.get("current_price") else None


def _parse_with_regex(text: str) -> Optional[dict]:
    """Fallback: parse DXY data using regex patterns."""
    result = {}

    # Current price (the first line matching "美元指数{price}")
    m = re.search(r'美元指数([\d.]+)', text)
    if m:
        result["current_price"] = float(m.group(1))

    # Change percent
    m = re.search(r'美元指数[\d.]+([+-][\d.]+%)', text)
    if m:
        result["change_percent"] = m.group(1)

    # Prev close (昨收)
    m = re.search(r'昨收\s*([\d.]+)', text)
    if m:
        result["prev_close"] = float(m.group(1))

    # Open (今开)
    m = re.search(r'今开\s*([\d.]+)', text)
    if m:
        result["open"] = float(m.group(1))

    # High (最高)
    m = re.search(r'最高\s*([\d.]+)', text)
    if m:
        result["high"] = float(m.group(1))

    # Low (最低)
    m = re.search(r'最低\s*([\d.]+)', text)
    if m:
        result["low"] = float(m.group(1))

    result["series_name"] = "美元指数"
    result["series_id"] = "DINIW"

    return result if result.get("current_price") else None