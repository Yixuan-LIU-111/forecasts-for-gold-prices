"""鹰鸽指数模块 + 落库（C-6，对齐 项目方案V1.0 §10.x 鹰鸽指数语义）。

流程：新闻文本 → 关键词词典打分 → 映射 [-0.5, +0.5] → 落库 hawk_dove_events。

- 默认用词典法（hawkish / dovish 关键词），无需 LLM 即可运行；
- 若配置了 LLM（ali_dashscope 等），可启用 LLM 精提取（惰性导入、可选）；
- 每条事件关联来源新闻 source_news_id（与 C-1 情感落库同源 news 表）。
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.tables import HawkDoveEvent, News

logger = logging.getLogger(__name__)

# 鹰派（收紧、利空黄金）→ 正向 score；鸽派（宽松、利多黄金）→ 负向 score
HAWKISH_TERMS = [
    "加息", "紧缩", "鹰派", "hike", "hawkish", "tighten", "tightening",
    "通胀", "inflation", "缩减", "taper", "缩表", "QT", "强硬",
]
DOVISH_TERMS = [
    "降息", "宽松", "鸽派", "cut", "dovish", "easing", "stimulus",
    "刺激", "宽松", "鸽派", "放缓", "pause", "QT结束", "转向",
]
# 加权：强信号词权重更高
STRONG_TERMS = {"加息", "降息", "hike", "cut", "鹰派", "鸽派", "hawkish", "dovish"}

SCORE_CAP = 0.5


def score_text(text: str) -> tuple[float, str, str, list[str]]:
    """对一段文本做鹰鸽打分，返回 (score, type, label, matched_terms)。

    score ∈ [-0.5, +0.5]：鹰派为正、鸽派为负。
    type ∈ {hawk, dove, neutral}；label ∈ {鹰派, 鸽派, 中性}。
    """
    if not text:
        return 0.0, "neutral", "中性", []
    lower = text.lower()
    matched: list[str] = []
    hawk_hits = dove_hits = 0
    for term in HAWKISH_TERMS:
        if re.search(re.escape(term.lower()), lower):
            matched.append(term)
            hawk_hits += 2 if term.lower() in STRONG_TERMS else 1
    for term in DOVISH_TERMS:
        if re.search(re.escape(term.lower()), lower):
            matched.append(term)
            dove_hits += 2 if term.lower() in STRONG_TERMS else 1
    if not matched:
        return 0.0, "neutral", "中性", []

    net = hawk_hits - dove_hits  # 鹰派多则正
    # 归一化：以最大可能强度粗略归一，clamp 到 [-0.5, 0.5]
    denom = max(hawk_hits, dove_hits, 1)
    score = max(-SCORE_CAP, min(SCORE_CAP, round(net / (denom * 2), 3)))
    if score > 0.05:
        return score, "hawk", "鹰派", matched
    if score < -0.05:
        return score, "dove", "鸽派", matched
    return 0.0, "neutral", "中性", matched


def process_news_to_events(db: Session, limit: int = 200) -> int:
    """遍历近期 news，对未处理的新闻做鹰鸽打分并落库 hawk_dove_events。

    已存在 source_news_id 的新闻跳过（幂等）。返回新写入事件数。
    """
    existing = {
        row[0]
        for row in db.execute(
            select(HawkDoveEvent.news_id).where(
                HawkDoveEvent.news_id.isnot(None)
            )
        ).all()
    }
    stmt = select(News).order_by(News.published_at.desc()).limit(limit)
    if existing:
        stmt = stmt.where(News.id.notin_(existing))
    rows = db.execute(stmt).scalars().all()

    inserted = 0
    for news in rows:
        text = " ".join(
            p for p in (news.title or "", news.content or "") if p
        )
        score, typ, label, _ = score_text(text)
        if typ == "neutral" and score == 0.0:
            # 中性且无关键词命中：仍记录一条中性事件，便于审计
            pass
        event = HawkDoveEvent(
            date=(news.published_at or datetime.now(timezone.utc)).date(),
            speaker=None,
            score=score,
            type=typ,
            label=label,
            summary=(news.title or "")[:500],
            news_id=news.id,
        )
        db.add(event)
        inserted += 1
    if inserted:
        db.commit()
    logger.info("鹰鸽指数：新增事件 %d 条（扫描 %d 条新闻）", inserted, len(rows))
    return inserted


def latest_events(db: Session, days: int = 30, limit: int = 50) -> list[dict]:
    """读取近期鹰鸽事件（供 API / 前端时间轴使用）。"""
    from datetime import timedelta

    since = (datetime.now(timezone.utc) - timedelta(days=days)).date()
    rows = (
        db.execute(
            select(HawkDoveEvent)
            .where(HawkDoveEvent.date >= since)
            .order_by(HawkDoveEvent.date.desc())
            .limit(limit)
        )
        .scalars()
        .all()
    )
    return [
        {
            "date": r.date.isoformat() if r.date else None,
            "speaker": r.speaker,
            "score": float(r.score) if r.score is not None else 0.0,
            "type": r.type,
            "label": r.label,
            "summary": r.summary,
        }
        for r in rows
    ]
