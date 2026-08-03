"""Parse VIX data from CBOE page HTML (Next.js RSC payload)."""

import json
import re
from datetime import datetime, timezone
from typing import Optional


def parse_vix_data(html: str) -> Optional[dict]:
    """Extract VIX data from CBOE page HTML.

    CBOE uses Next.js which embeds data in RSC (React Server Components)
    payload chunks via self.__next_f.push() calls.  The VIX time series
    lives inside a dehydrated React Query cache with this shape:

        {"VIX": {"symbolData": [{"x": epoch_ms, "val-VIX": ..., "pct-VIX": ...}, ...]}}

    Returns a dict with the latest data point and summary info.
    """
    if not html:
        return None

    raw = _extract_rsc_payload(html)
    if raw is None:
        return None

    vix_data = _find_vix_data(raw)
    if vix_data is None:
        return None

    symbol_data = vix_data.get("symbolData", [])
    if not symbol_data:
        return None

    # Last point is the most current
    latest = symbol_data[-1]

    # Compute aggregate stats from the full series
    vals = [p["val-VIX"] for p in symbol_data if "val-VIX" in p]

    ts = latest.get("x", 0)
    dt = datetime.fromtimestamp(ts / 1000, tz=timezone.utc)

    result = {
        "vix_spot_price": latest.get("val-VIX"),
        "data_as_of": dt.strftime("%Y-%m-%d %H:%M UTC"),
        "data_timestamp_ms": ts,
    }

    if vals:
        result["low_today"] = round(min(vals), 2)
        result["high_today"] = round(max(vals), 2)
        result["open"] = round(vals[0], 2)
        result["prev_close"] = round(vals[0], 2) if len(vals) > 1 else None
        # approximate change from first point of the day
        change = latest.get("val-VIX", 0) - vals[0]
        result["change_amount"] = round(change, 2)
        if vals[0]:
            result["change_percent"] = round((change / vals[0]) * 100, 2)

    return result


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _extract_rsc_payload(html: str) -> Optional[str]:
    """Join all self.__next_f.push([1,"..."]) chunks and unescape."""
    chunks = re.findall(
        r'self\.__next_f\.push\(\[1,\"(.*?)\"\]\)', html, re.DOTALL
    )
    if not chunks:
        return None
    raw = "".join(chunks)

    # Unescape JSON-level escapes
    raw = raw.replace('\\"', '"')
    raw = raw.replace("\\/", "/")
    raw = raw.replace("\\n", " ")
    raw = raw.replace("\\t", " ")

    # Decode \\uXXXX unicode escapes
    raw = re.sub(r"\\u([0-9a-fA-F]{4})", lambda m: chr(int(m.group(1), 16)), raw)

    return raw


def _find_vix_data(text: str) -> Optional[dict]:
    """Locate and parse the VIX JSON object inside the RSC payload.

    The structure appears inside a React Query dehydrated cache:

        "data":{"VIX":{"symbolData":[...]}}

    We locate 'symbolData' and walk backward to find the enclosing object.
    """
    idx = text.find('"symbolData"')
    if idx < 0:
        return None

    # Walk backward to find the enclosing '{' that starts the VIX object
    brace_depth = 0
    start = idx
    for i in range(idx, -1, -1):
        if text[i] == "}":
            brace_depth += 1
        elif text[i] == "{":
            brace_depth -= 1
            if brace_depth < 0:
                start = i
                break
    if brace_depth >= 0:
        return None

    # Now walk forward to find the matching '}'
    brace_depth = 0
    end = start
    for i in range(start, len(text)):
        if text[i] == "{":
            brace_depth += 1
        elif text[i] == "}":
            brace_depth -= 1
            if brace_depth == 0:
                end = i + 1
                break
    if brace_depth != 0:
        return None

    obj_str = text[start:end]
    try:
        return json.loads(obj_str)
    except json.JSONDecodeError:
        return None