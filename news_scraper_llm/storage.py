"""
结果持久化：JSON + CSV
"""
import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Sequence

from .models import AnalyzedNewsItem


def save_results(
    items: Sequence[AnalyzedNewsItem],
    output_dir: str,
    write_json: bool = True,
    write_csv: bool = True,
) -> dict[str, str]:
    """
    保存分析结果。

    Returns:
        {"json": path, "csv": path} 实际写入的文件路径
    """
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    written: dict[str, str] = {}

    records = [item.model_dump(mode="json") for item in items]

    if write_json:
        json_path = out / f"news_sentiment_{timestamp}.json"
        with json_path.open("w", encoding="utf-8") as f:
            json.dump({
                "generated_at": datetime.utcnow().isoformat(),
                "count": len(records),
                "data": records,
            }, f, ensure_ascii=False, indent=2)
        written["json"] = str(json_path)

    if write_csv:
        csv_path = out / f"news_sentiment_{timestamp}.csv"
        if records:
            headers = list(records[0].keys())
            with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=headers)
                writer.writeheader()
                writer.writerows(records)
        written["csv"] = str(csv_path)

    return written
