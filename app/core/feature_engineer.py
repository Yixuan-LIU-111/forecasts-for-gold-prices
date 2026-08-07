"""特征工程（对齐项目方案 9.4）。

从 market_data / factor_data 表组装特征 DataFrame，供模型推理使用。
"""
from __future__ import annotations

import logging
from typing import Optional

import pandas as pd
from sqlalchemy import select, desc
from sqlalchemy.orm import Session

from app.models.database import MarketData, FactorData, News

logger = logging.getLogger(__name__)


def load_recent_prices(
    db: Session, symbol: str = "XAUUSD", limit: int = 500
) -> pd.DataFrame:
    """加载最近 N 条价格序列。"""
    stmt = (
        select(MarketData.timestamp, MarketData.price, MarketData.volume)
        .where(MarketData.symbol == symbol)
        .order_by(desc(MarketData.timestamp))
        .limit(limit)
    )
    rows = db.execute(stmt).all()
    if not rows:
        return pd.DataFrame(columns=["timestamp", "price", "volume"])
    df = pd.DataFrame(rows, columns=["timestamp", "price", "volume"])
    df = df.sort_values("timestamp").reset_index(drop=True)
    return df


def load_latest_news_sentiment(db: Session, window_hours: int = 72) -> dict:
    """从 news 表聚合「实时新闻情感因子」。

    取最近 window_hours 内、已做 LLM 情感分析的新闻，按置信度加权求均值。
    这是 news_scraper_llm 实时爬取落库的数据，规避对 factor_data 静态种子行的依赖。

    返回 {"value": float, "count": int, "source": str, "timestamp": datetime|None}
    """
    from datetime import datetime, timedelta, timezone

    cutoff = datetime.now(timezone.utc) - timedelta(hours=window_hours)
    rows = db.execute(
        select(News.published_at, News.sentiment_score, News.confidence)
        .where(News.sentiment_score.isnot(None))
        .order_by(desc(News.published_at))
        .limit(200)
    ).all()

    def _as_aware(dt):
        if dt is None:
            return None
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)

    recent = [
        (pa, s, c) for (pa, s, c) in rows
        if _as_aware(pa) is not None and _as_aware(pa) >= cutoff
    ]
    if not recent:
        return {"value": 0.0, "count": 0, "source": "news_scraper_llm", "timestamp": None}

    vals = [float(s) for (_, s, _) in recent]
    weights = [float(c) if c is not None else 0.5 for (_, _, c) in recent]
    wsum = sum(weights)
    wmean = (sum(v * w for v, w in zip(vals, weights)) / wsum) if wsum > 0 else (
        sum(vals) / len(vals)
    )
    return {
        "value": round(float(wmean), 4),
        "count": len(recent),
        "source": "news_scraper_llm",
        "timestamp": recent[0][0],
    }


def load_latest_factors(db: Session) -> dict[str, dict]:
    """加载各因子的最新值。返回 {indicator_code: {value, change, change_pct, ...}}。"""
    codes = ["DXY", "TIPS10Y", "VIX", "GPR", "hawk_dove"]
    out: dict[str, dict] = {}
    for code in codes:
        stmt = (
            select(FactorData)
            .where(FactorData.indicator_code == code)
            .order_by(desc(FactorData.timestamp))
            .limit(2)
        )
        rows = db.execute(stmt).scalars().all()
        if not rows:
            continue
        latest = rows[0]
        prev = rows[1] if len(rows) > 1 else None
        out[code] = {
            "value": latest.value,
            "change": latest.change if latest.change is not None else (
                latest.value - prev.value if prev and prev.value else 0.0
            ),
            "change_pct": latest.change_pct,
            "timestamp": latest.timestamp,
            "source": latest.source,
        }

    # 实时新闻情感：直接由 news 表聚合，覆盖任何静态 sentiment 因子行
    sent = load_latest_news_sentiment(db)
    out["sentiment"] = {
        "value": sent["value"],
        "change": 0.0,
        "change_pct": None,
        "timestamp": sent["timestamp"],
        "source": sent["source"],
        "count": sent["count"],
    }
    return out


def build_features(db: Session) -> pd.DataFrame:
    """组装单条推理特征（最新时刻点）。

    返回单行 DataFrame，含价格、因子、衍生特征列。
    """
    prices = load_recent_prices(db, limit=120)
    factors = load_latest_factors(db)

    if prices.empty:
        logger.warning("无价格数据，特征组装失败")
        return pd.DataFrame()

    feat: dict = {}

    # ===== 价格序列特征 =====
    p = prices["price"]
    feat["price"] = float(p.iloc[-1])
    feat["return_30min"] = (
        float(p.iloc[-1] / p.iloc[-min(30, len(p)) - 1] - 1)
        if len(p) > 30
        else 0.0
    )
    feat["volatility_30min"] = (
        float(p.pct_change().rolling(30).std().iloc[-1]) if len(p) > 30 else 0.0
    )
    feat["momentum_5m"] = (
        float(p.iloc[-1] / p.iloc[-6] - 1) if len(p) > 5 else 0.0
    )
    feat["momentum_10m"] = (
        float(p.iloc[-1] / p.iloc[-11] - 1) if len(p) > 10 else 0.0
    )

    # ===== 因子特征 =====
    feat["dxy"] = factors.get("DXY", {}).get("value", 0.0)
    feat["dxy_return"] = factors.get("DXY", {}).get("change", 0.0) or 0.0
    feat["tips_yield"] = factors.get("TIPS10Y", {}).get("value", 0.0)
    feat["tips_change"] = factors.get("TIPS10Y", {}).get("change", 0.0) or 0.0
    feat["vix"] = factors.get("VIX", {}).get("value", 0.0)
    feat["vix_high_vol"] = 1 if feat["vix"] > 30 else 0
    feat["gpr_score"] = factors.get("GPR", {}).get("value", 0.0)
    feat["gpr_event_flag"] = 1 if feat["gpr_score"] > 200 else 0
    feat["sentiment_score"] = factors.get("sentiment", {}).get("value", 0.0)
    feat["hawkish_score"] = factors.get("hawk_dove", {}).get("value", 0.0)
    feat["news_count_recent"] = int(factors.get("sentiment", {}).get("count", 0) or 0)

    # ===== 交互特征 =====
    feat["vix_dxy"] = feat["vix"] * feat["dxy_return"]
    feat["gpr_vix"] = feat["gpr_score"] * feat["vix"]

    return pd.DataFrame([feat])


def get_feature_columns() -> list[str]:
    """特征列顺序（与训练对齐）。"""
    return [
        "price", "return_30min", "volatility_30min", "momentum_5m",
        "momentum_10m", "dxy", "dxy_return", "tips_yield", "tips_change",
        "vix", "vix_high_vol", "gpr_score", "gpr_event_flag",
        "sentiment_score", "hawkish_score", "news_count_recent",
        "vix_dxy", "gpr_vix",
    ]
