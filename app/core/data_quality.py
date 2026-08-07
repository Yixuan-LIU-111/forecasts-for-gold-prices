"""数据质量校验（B-9，对齐 项目方案V1.0 §8.x 数据质量）。

针对 market_data 做两类监控：
- 断档检测：相邻两条记录间隔 > max_gap_minutes（默认 3 分钟）→ 告警
- 价格跳变检测：相邻两条价格涨跌幅 > threshold_pct（默认 5%）→ 标记

说明：market_data 无独立「标记」列，故检测结果以「报告 + 告警日志」形式输出，
供调度器/监控系统消费；如需持久化可后续扩展 data_quality_issues 表（本任务不含）。
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Optional

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.tables import MarketData

logger = logging.getLogger(__name__)


def _load_series(db: Session, symbol: str) -> pd.DataFrame:
    rows = db.execute(
        select(MarketData.timestamp, MarketData.price)
        .where(MarketData.symbol == symbol)
        .order_by(MarketData.timestamp)
    ).all()
    if not rows:
        return pd.DataFrame(columns=["timestamp", "price"])
    df = pd.DataFrame(rows, columns=["timestamp", "price"])
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df["price"] = pd.to_numeric(df["price"], errors="coerce")
    return df


def find_gaps(db: Session, symbol: str, max_gap_minutes: int = 3) -> list[dict]:
    """返回 market_data 中 symbol 的断档区间（间隔 > max_gap_minutes）。"""
    df = _load_series(db, symbol)
    if len(df) < 2:
        return []
    df = df.sort_values("timestamp").reset_index(drop=True)
    gaps: list[dict] = []
    for i in range(1, len(df)):
        prev, cur = df.iloc[i - 1], df.iloc[i]
        gap = (cur["timestamp"] - prev["timestamp"]).total_seconds() / 60.0
        if gap > max_gap_minutes:
            gaps.append({
                "symbol": symbol,
                "from": prev["timestamp"].isoformat(),
                "to": cur["timestamp"].isoformat(),
                "gap_minutes": round(gap, 1),
            })
    return gaps


def find_price_jumps(db: Session, symbol: str, threshold_pct: float = 5.0) -> list[dict]:
    """返回 market_data 中 symbol 的价格跳变点（|涨跌幅| > threshold_pct）。"""
    df = _load_series(db, symbol)
    df = df.dropna(subset=["price"]).sort_values("timestamp").reset_index(drop=True)
    if len(df) < 2:
        return []
    jumps: list[dict] = []
    for i in range(1, len(df)):
        prev, cur = df.iloc[i - 1], df.iloc[i]
        if prev["price"] == 0 or pd.isna(prev["price"]):
            continue
        chg = (cur["price"] - prev["price"]) / prev["price"] * 100.0
        if abs(chg) > threshold_pct:
            jumps.append({
                "symbol": symbol,
                "timestamp": cur["timestamp"].isoformat(),
                "prev_price": float(prev["price"]),
                "price": float(cur["price"]),
                "change_pct": round(chg, 2),
            })
    return jumps


def run_quality_checks(
    db: Session,
    symbols: Optional[list[str]] = None,
    max_gap_minutes: int = 3,
    threshold_pct: float = 5.0,
) -> dict:
    """对一组 symbol 运行断档 + 跳变检查，汇总并告警，返回报告。"""
    if symbols is None:
        # 取 market_data 中实际存在的 symbol
        symbols = [
            r[0] for r in db.execute(
                select(MarketData.symbol).distinct()
            ).all()
        ]
    report = {"generated_at": datetime.now().isoformat(), "symbols": {}, "alerts": []}
    for sym in symbols:
        gaps = find_gaps(db, sym, max_gap_minutes)
        jumps = find_price_jumps(db, sym, threshold_pct)
        report["symbols"][sym] = {
            "gaps": len(gaps),
            "price_jumps": len(jumps),
        }
        for g in gaps:
            msg = f"[断档告警] {sym}: {g['from']} ~ {g['to']} 间隔 {g['gap_minutes']} 分钟"
            logger.warning(msg)
            report["alerts"].append({"type": "gap", **g})
        for j in jumps:
            msg = f"[跳变标记] {sym}: {j['timestamp']} 涨跌 {j['change_pct']}%"
            logger.warning(msg)
            report["alerts"].append({"type": "jump", **j})
    report["total_alerts"] = len(report["alerts"])
    return report
