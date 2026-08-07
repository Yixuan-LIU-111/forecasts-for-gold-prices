"""实时新闻情感因子：把 news_scraper_llm 落库的实时情感聚合为规范化因子。

双写策略（单一事实来源 + 兼容视图）：
1. 实时读取：app/core/feature_engineer.py::load_latest_news_sentiment
   直接从 news 表聚合，线上推理无需任何中间表即可消费最新情感。
2. 规范化落库：本模块的 refresh_sentiment_factor 将聚合结果写入
   factor_data(indicator_code="sentiment")，作为可被 factor_data 体系
   （归因、历史回溯、离线核对）统一读取的「情感因子行」。

二者数值同源（同一聚合逻辑），前者保证实时，后者保证与 factor_data 视图一致。
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, desc, select
from sqlalchemy.orm import Session

from app.models.database import FactorData, News

logger = logging.getLogger(__name__)


def aggregate_recent_sentiment(db: Session, window_hours: int = 72) -> dict:
    """聚合最近 window_hours 内已分析新闻的情感（置信度加权均值）。

    返回 {"value": float, "count": int}；无数据则 value=0.0, count=0。
    """
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
        return {"value": 0.0, "count": 0}

    vals = [float(s) for (_, s, _) in recent]
    weights = [float(c) if c is not None else 0.5 for (_, _, c) in recent]
    wsum = sum(weights)
    wmean = (sum(v * w for v, w in zip(vals, weights)) / wsum) if wsum > 0 else (
        sum(vals) / len(vals)
    )
    return {"value": round(float(wmean), 4), "count": len(recent)}


def refresh_sentiment_factor(db: Session, window_hours: int = 72) -> dict:
    """将实时聚合情感写入 factor_data(indicator_code="sentiment")。

    以「单一实时值」覆盖历史 sentiment 因子行（因子体系将其视为当前快照）。
    失败时回滚并告警，不影响主爬取/推理链路。
    """
    agg = aggregate_recent_sentiment(db, window_hours)
    try:
        db.execute(
            delete(FactorData).where(FactorData.indicator_code == "sentiment")
        )
        db.add(
            FactorData(
                indicator_code="sentiment",
                indicator_name="新闻情感指数",
                category="佐证表象",
                timestamp=datetime.now(timezone.utc),
                value=agg["value"],
                value_type="情感得分",
                source="news_scraper_llm",
                update_frequency="实时",
                realtime_inference=True,
            )
        )
        db.commit()
        logger.info(
            "刷新情感因子: value=%.3f count=%d", agg["value"], agg["count"]
        )
    except Exception as e:  # noqa: BLE001
        db.rollback()
        logger.warning("情感因子刷新失败（不影响推理）: %s", e)
    return agg
