"""Parse GPR data from Excel file downloaded from Iacoviello's website."""

import logging
from typing import Optional

import xlrd

logger = logging.getLogger(__name__)

# Column indices in the Excel file
COL_DAY = 0         # 'DAY' - date YYYYMMDD
COL_N10D = 1        # 'N10D' - number of articles
COL_GPRD = 2        # 'GPRD' - Daily GPR Index
COL_GPRD_ACT = 3    # 'GPRD_ACT' - Daily GPR Acts
COL_GPRD_THREAT = 4 # 'GPRD_THREAT' - Daily GPR Threats
COL_DATE = 5        # 'date' - Excel serial date
COL_GPRD_MA30 = 6   # 'GPRD_MA30' - 30-day moving average
COL_GPRD_MA7 = 7    # 'GPRD_MA7' - 7-day moving average
COL_EVENT = 8       # 'event' - major event label


def parse_gpr_excel(file_content: bytes) -> Optional[dict]:
    """Parse the GPR daily data Excel file and extract the latest record.

    The Excel file has columns:
        DAY, N10D, GPRD, GPRD_ACT, GPRD_THREAT, date,
        GPRD_MA30, GPRD_MA7, event, var_name, var_label

    Args:
        file_content: Raw bytes of the .xls file.

    Returns:
        Dict with latest GPR data, or None on failure.
    """
    try:
        workbook = xlrd.open_workbook(file_contents=file_content)
    except Exception as e:
        logger.error("Failed to open Excel workbook: %s", e)
        return None

    sheet = workbook.sheet_by_index(0)
    if sheet.nrows < 2:
        logger.error("Excel file has insufficient rows: %d", sheet.nrows)
        return None

    # Read header row to verify structure
    header = [str(sheet.cell(0, j).value).strip() for j in range(sheet.ncols)]
    logger.info("Excel columns: %s", header)

    # Get the last data row (row nrows - 1)
    last_row = sheet.nrows - 1
    raw = {}
    for j in range(sheet.ncols):
        raw[header[j]] = sheet.cell(last_row, j).value

    logger.info("Last raw row: %s", raw)

    # Parse date from YYYYMMDD format
    day_str = str(int(raw.get("DAY", 0)))
    date_str = f"{day_str[:4]}-{day_str[4:6]}-{day_str[6:8]}" if len(day_str) == 8 else day_str

    # Build result
    result = {
        "date": date_str,
        "day_raw": day_str,
        "n10d": int(raw.get("N10D", 0)),
        "gprd": round(float(raw.get("GPRD", 0)), 4),
        "gprd_act": round(float(raw.get("GPRD_ACT", 0)), 4),
        "gprd_threat": round(float(raw.get("GPRD_THREAT", 0)), 4),
        "gprd_ma30": round(float(raw.get("GPRD_MA30", 0)), 4),
        "gprd_ma7": round(float(raw.get("GPRD_MA7", 0)), 4),
        "event": str(raw.get("event", "")),
    }

    # Also get the previous row for comparison
    if sheet.nrows >= 3:
        prev_row = sheet.nrows - 2
        prev_raw = {}
        for j in range(sheet.ncols):
            prev_raw[header[j]] = sheet.cell(prev_row, j).value
        result["prev_date"] = str(int(prev_raw.get("DAY", 0)))[:8]
        result["prev_gprd"] = round(float(prev_raw.get("GPRD", 0)), 4)

    # Extract series metadata
    result["series_name"] = "Geopolitical Risk Index (GPR)"
    result["series_id"] = "GPRD"
    result["source"] = "Matteo Iacoviello"
    result["last_update"] = "July 27, 2026"  # from page text

    return result


def parse_gpr_history(file_content: bytes, limit: int = 30) -> Optional[list]:
    """Parse the GPR Excel file and return recent records.

    Args:
        file_content: Raw bytes of the .xls file.
        limit: Number of recent records to return.

    Returns:
        List of recent records, or None on failure.
    """
    try:
        workbook = xlrd.open_workbook(file_contents=file_content)
    except Exception as e:
        logger.error("Failed to open Excel workbook: %s", e)
        return None

    sheet = workbook.sheet_by_index(0)
    if sheet.nrows < 2:
        return None

    header = [str(sheet.cell(0, j).value).strip() for j in range(sheet.ncols)]
    records = []

    start = max(1, sheet.nrows - limit - 1)
    for i in range(start, sheet.nrows):
        row = {}
        for j in range(sheet.ncols):
            row[header[j]] = sheet.cell(i, j).value
        day_str = str(int(row.get("DAY", 0)))
        date_str = f"{day_str[:4]}-{day_str[4:6]}-{day_str[6:8]}" if len(day_str) == 8 else day_str
        row["date_formatted"] = date_str
        records.append(row)

    return records