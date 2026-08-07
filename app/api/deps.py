"""API 共享依赖与序列化辅助函数。

将 ORM 对象序列化为对齐 demo_data 的 dict，确保响应结构零差异。
"""
from __future__ import annotations

import logging
import urllib.parse
from typing import Any, Optional

from sqlalchemy import select, desc, func
from sqlalchemy.orm import Session

from app.models.database import (
    MarketData, FactorData, News, Signal, BacktestResult, HawkDoveEvent, DataSource,
)
from app.models.schemas import ApiResponse

logger = logging.getLogger(__name__)


def _iso(dt) -> str:
    """转 ISO 字符串（对齐 demo_data 格式）。"""
    if dt is None:
        return ""
    if hasattr(dt, "isoformat"):
        s = dt.isoformat()
        # 去掉时区后缀以匹配 demo_data（无 +00:00）
        return s.replace("+00:00", "").replace("T", "T")
    return str(dt)


def serialize_signal(s: Optional[Signal]) -> Optional[dict]:
    if s is None:
        return None
    return {
        "timestamp": _iso(s.timestamp),
        "direction": s.direction,
        "direction_en": s.direction_en,
        "probability": s.probability,
        "strength": s.strength,
        "position": s.position,
        "position_pct": s.position_pct,
        "bull_bear_score": s.bull_bear_score,
        "confidence": s.confidence,
        "confidence_value": s.confidence_value,
        "model": s.model,
        "attribution": s.attribution or [],
        "stop_loss": s.stop_loss,
        "take_profit": s.take_profit,
    }


def serialize_market(db: Session, range_hours: str = "4h") -> dict:
    """构造行情响应（对齐 market.json）。"""
    period_map = {"1h": 12, "4h": 48, "1d": 96, "3d": 288, "7d": 672}
    limit = period_map.get(range_hours, 48)

    rows = db.execute(
        select(MarketData)
        .where(MarketData.symbol == "XAUUSD")
        .order_by(desc(MarketData.timestamp))
        .limit(limit)
    ).scalars().all()
    rows = list(reversed(rows))

    if not rows:
        logger.warning("serialize_market: market_data 表无 XAUUSD 数据！返回空行情")
        return {
            "symbol": "XAU/USD", "current_price": 0, "change": 0, "change_pct": 0,
            "high_24h": 0, "low_24h": 0, "open_24h": 0, "prev_close": 0,
            "timestamp": _iso(None), "prices": [],
        }
    logger.info("serialize_market: 取到 %d 条价格点", len(rows))

    prices = [float(r.price) for r in rows if r.price is not None]
    current = prices[-1] if prices else 0
    open_24h = prices[0] if prices else 0
    prev_close = prices[0] if prices else 0
    change = current - prev_close if prev_close else 0
    change_pct = round(change / prev_close * 100, 2) if prev_close else 0

    return {
        "symbol": "XAU/USD",
        "current_price": round(current, 2),
        "change": round(change, 2),
        "change_pct": change_pct,
        "high_24h": round(max(prices), 2) if prices else 0,
        "low_24h": round(min(prices), 2) if prices else 0,
        "open_24h": round(open_24h, 2),
        "prev_close": round(prev_close, 2),
        "timestamp": _iso(rows[-1].timestamp),
        "prices": [
            {"time": _iso(r.timestamp), "price": float(r.price), "volume": int(r.volume or 0)}
            for r in rows
        ],
    }


def serialize_factors(db: Session) -> dict:
    """构造 6 因子响应（对齐 factors.json）。"""
    order = [
        ("DXY", "DXY", "美元指数", "", "red"),
        ("TIPS10Y", "TIPS", "实际利率", "%", "green"),
        ("VIX", "VIX", "恐慌指数", "", "gray"),
        ("GPR", "GPR", "地缘风险", "", "red"),
        ("sentiment", "sentiment", "新闻情感", "", "green"),
        ("hawk_dove", "hawk_dove", "鹰鸽指数", "", "green"),
    ]
    factors = []
    ts = None
    for code, name, label, unit, default_color in order:
        rows = db.execute(
            select(FactorData)
            .where(FactorData.indicator_code == code)
            .order_by(desc(FactorData.timestamp))
            .limit(2)
        ).scalars().all()
        if not rows:
            logger.warning("serialize_factors: 因子 %s 在 factor_data 表中无数据！", code)
            continue
        latest = rows[0]
        prev = rows[1] if len(rows) > 1 else None
        if ts is None:
            ts = latest.timestamp
        change = latest.change
        if change is None and prev and prev.value:
            change = latest.value - prev.value
        change_pct = latest.change_pct
        if change_pct is None and prev and prev.value:
            change_pct = round(change / prev.value * 100, 2) if prev.value else None

        trend = "up" if (change or 0) > 0 else ("down" if (change or 0) < 0 else "flat")
        # 趋势色：利空 red / 利多 green / 中性 gray
        # DXY/TIPS/VIX/GPR 上升利空(红)；sentiment 上升利多(绿)；hawk_dove 负值利多(绿)
        if name == "DXY" or name == "TIPS" or name == "VIX" or name == "GPR":
            trend_color = "red" if (change or 0) > 0 else ("green" if (change or 0) < 0 else "gray")
        else:
            trend_color = "green" if (change or 0) > 0 else ("red" if (change or 0) < 0 else "gray")

        factors.append({
            "name": name,
            "label": label,
            "value": float(latest.value) if latest.value is not None else 0,
            "change": round(float(change), 2) if change is not None else 0,
            "change_pct": round(float(change_pct), 2) if change_pct is not None else None,
            "trend": trend,
            "trend_color": trend_color,
            "unit": unit,
            "source": latest.source or "",
        })

    if len(factors) < 6:
        logger.warning("serialize_factors: 仅取到 %d 个因子（期望 6）", len(factors))
    else:
        logger.info("serialize_factors: 取到 %d 个因子", len(factors))
    return {"timestamp": _iso(ts), "factors": factors}


def serialize_news(db: Session, limit: int = 20, offset: int = 0) -> list[dict]:
    rows = db.execute(
        select(News).order_by(desc(News.published_at)).offset(offset).limit(limit)
    ).scalars().all()
    if not rows:
        logger.warning("serialize_news: news 表无数据！")
    else:
        logger.info("serialize_news: 取到 %d 条新闻", len(rows))
    out = []
    for i, n in enumerate(rows, start=1):
        url = n.url or ""
        if not url.startswith(("http://", "https://")):
            # 无原文链接时回退到搜索链接，保证标题始终可点击
            url = "https://www.google.com/search?q=" + urllib.parse.quote(n.title or "")
        out.append({
            "id": f"n{n.id:03d}",
            "title": n.title,
            "title_zh": n.title_zh or n.title,
            "sentiment": n.sentiment or "neutral",
            "sentiment_label": n.sentiment_label or "中性",
            "sentiment_score": float(n.sentiment_score or 0),
            "source": n.source or "",
            "published_at": _iso(n.published_at),
            "url": url,
            "confidence": float(n.confidence or 0),
            "is_important": bool(n.is_important),
            "key_sentence": n.key_sentence or "",
            "topic": n.topic or "Other",
            "hawk_dove": n.hawk_dove,
            "hawk_dove_score": n.hawk_dove_score,
        })
    return out


def serialize_accuracy(db: Session, window: str = "7d") -> dict:
    bt = db.execute(
        select(BacktestResult).order_by(desc(BacktestResult.created_at), desc(BacktestResult.id)).limit(1)
    ).scalars().first()
    if bt and bt.accuracy:
        logger.info("serialize_accuracy: 命中回测 run_id=%s", bt.run_id)
        return bt.accuracy
    logger.warning("serialize_accuracy: 无回测记录，返回默认值")
    return {
        "overall_7d": 62.5,
        "overall_30d": 58.2,
        "bullish_accuracy": 60.5,
        "bearish_accuracy": 55.8,
        "neutral_accuracy": 0,
        "sample_7d": 0,
        "sample_30d": 0,
        "sample_bullish": 0,
        "sample_bearish": 0,
        "data_mode": "synthetic",
    }


def serialize_pnl(db: Session) -> dict:
    bt = db.execute(
        select(BacktestResult).order_by(desc(BacktestResult.created_at), desc(BacktestResult.id)).limit(1)
    ).scalars().first()
    if bt and bt.pnl_distribution:
        logger.info("serialize_pnl: 命中回测 run_id=%s", bt.run_id)
        return bt.pnl_distribution
    logger.warning("serialize_pnl: 无回测记录，返回默认值")
    return {"bins": [-60, -40, -20, 0, 20, 40, 60], "counts": [5, 12, 25, 38, 28, 15, 8]}


def serialize_trades(db: Session) -> list[dict]:
    bt = db.execute(
        select(BacktestResult).order_by(desc(BacktestResult.created_at), desc(BacktestResult.id)).limit(1)
    ).scalars().first()
    if bt and bt.trade_details:
        logger.info("serialize_trades: 命中回测 run_id=%s，%d 笔交易", bt.run_id, len(bt.trade_details))
        return bt.trade_details
    logger.warning("serialize_trades: 无回测记录，返回空列表")
    return []


def serialize_hawk_dove_events(db: Session, days: int = 7) -> list[dict]:
    rows = db.execute(
        select(HawkDoveEvent).order_by(desc(HawkDoveEvent.date)).limit(max(days, 20))
    ).scalars().all()
    if rows:
        return [
            {
                "date": str(e.date),
                "speaker": e.speaker or "",
                "score": float(e.score or 0),
                "type": e.type or "dove",
                "label": e.label or "鸽派",
                "summary": e.summary or "",
            }
            for e in rows
        ]
    return [
        {"date": "2026-07-24", "speaker": "鲍威尔", "score": 0.35, "type": "dove", "label": "鸽派", "summary": "暗示9月可能降息"},
        {"date": "2026-07-25", "speaker": "沃勒", "score": -0.42, "type": "hawk", "label": "鹰派", "summary": "通胀仍具粘性，不急于降息"},
        {"date": "2026-07-26", "speaker": "威廉姆斯", "score": 0.28, "type": "dove", "label": "鸽派", "summary": "经济数据支持温和政策"},
        {"date": "2026-07-27", "speaker": "鲍曼", "score": -0.15, "type": "hawk", "label": "鹰派", "summary": "需看到更多通胀进展"},
        {"date": "2026-07-28", "speaker": "戴利", "score": 0.10, "type": "dove", "label": "鸽派", "summary": "劳动力市场正在正常化"},
    ]


def range_hours_to_period(range_hours: str) -> str:
    return {"1h": "1h", "4h": "4h", "1d": "1d", "3d": "3d", "7d": "7d"}.get(range_hours, "4h")


def serialize_data_sources(db: Session) -> list[dict]:
    rows = db.execute(
        select(DataSource).order_by(DataSource.id)
    ).scalars().all()
    if not rows:
        logger.warning("serialize_data_sources: data_sources 表无数据！")
    return [
        {
            "indicator_code": r.indicator_code,
            "indicator_name": r.indicator_name,
            "source_name": r.source_name,
            "source_url": r.source_url,
            "update_frequency": r.update_frequency,
            "realtime": bool(r.realtime),
            "description": r.description,
        }
        for r in rows
    ]
