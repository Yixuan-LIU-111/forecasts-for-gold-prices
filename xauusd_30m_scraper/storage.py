"""落盘：实时报价快照 + 30 分钟 K 线（最新 + 历史 JSONL）。

文件：
- xauusd_30m_latest_quote.json：最新一笔报价（覆盖写）
- xauusd_30m_latest_bar.json  ：当前 forming / 最近一根 bar（覆盖写）
- xauusd_30m_bars.jsonl       ：已闭合 bar 历史（追加写）
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from . import config
from .models import Bar, Quote

logger = logging.getLogger(__name__)


def save_latest_quote(quote: Quote) -> Path:
    config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(str(config.LATEST_QUOTE_FILE), "w", encoding="utf-8") as f:
        json.dump(quote.to_dict(), f, ensure_ascii=False, indent=2)
    logger.debug("最新报价已保存: %s", config.LATEST_QUOTE_FILE)
    return config.LATEST_QUOTE_FILE


def save_latest_bar(bar: Bar) -> Path:
    config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(str(config.LATEST_BAR_FILE), "w", encoding="utf-8") as f:
        json.dump(bar.to_dict(), f, ensure_ascii=False, indent=2)
    return config.LATEST_BAR_FILE


def append_completed_bar(bar: Bar) -> Path:
    """将已闭合的 bar 追加写入历史 JSONL。"""
    config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    rec = {**bar.to_dict(), "_saved_at": datetime.now(timezone.utc).isoformat()}
    with open(str(config.BARS_HISTORY_FILE), "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    logger.debug("已完成 bar 已追加: %s", bar.timestamp)
    return config.BARS_HISTORY_FILE


def load_bars() -> List[Bar]:
    """加载全部 bar（历史 + 最新 forming），按时间升序、按 timestamp 去重。"""
    bars: List[Bar] = []
    if config.BARS_HISTORY_FILE.exists():
        try:
            with open(str(config.BARS_HISTORY_FILE), encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        bars.append(Bar(**json.loads(line)))
                    except Exception as e:
                        logger.warning("跳过损坏的 bar 记录: %s", e)
        except Exception as e:
            logger.error("读取 bar 历史失败: %s", e)

    # 合并最新 bar（可能是未完成的 forming bar，比历史中的同窗口记录更新）
    if config.LATEST_BAR_FILE.exists():
        try:
            lb = Bar(**json.loads(open(str(config.LATEST_BAR_FILE), encoding="utf-8").read()))
            seen = {b.timestamp for b in bars}
            if lb.timestamp not in seen:
                bars.append(lb)
            else:
                for i, b in enumerate(bars):
                    if b.timestamp == lb.timestamp:
                        bars[i] = lb
                        break
        except Exception as e:
            logger.warning("读取最新 bar 失败: %s", e)

    bars.sort(key=lambda b: b.timestamp)
    return bars


def load_latest_quote() -> Optional[dict]:
    if not config.LATEST_QUOTE_FILE.exists():
        return None
    try:
        with open(str(config.LATEST_QUOTE_FILE), encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error("读取最新报价失败: %s", e)
        return None
