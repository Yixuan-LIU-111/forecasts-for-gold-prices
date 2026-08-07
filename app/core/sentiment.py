"""新闻情感分析与鹰鸽指数提取。

LLM 不可用时降级为关键词规则引擎，保证系统可用。
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Optional

from app.config import settings
from app.core.title_summary import summarize_title

logger = logging.getLogger(__name__)

# 利多/利空关键词
BULL_KEYWORDS = [
    "cut rates", "rate cut", "dovish", "easing", "stimulus", "rally",
    "surge", "safe haven", "geopolitical tension", "inflation hedge",
    "buy gold", "demand rises", "降息", "鸽派", "避险", "上涨",
]
BEAR_KEYWORDS = [
    "hike rates", "rate hike", "hawkish", "tightening", "strong dollar",
    "risk appetite", "sell gold", "decline", "drop", "hawkish tone",
    "加息", "鹰派", "美元走强", "下跌",
]
# 鹰派/鸽派信号
HAWK_KEYWORDS = ["hawkish", "rate hike", "tightening", "inflation sticky", "鹰派", "加息", "通胀粘性"]
DOVE_KEYWORDS = ["dovish", "rate cut", "easing", "prepared to cut", "鸽派", "降息", "宽松"]


@dataclass
class SentimentResult:
    sentiment: str  # bullish/bearish/neutral
    sentiment_label: str  # 利多/利空/中性
    sentiment_score: float  # -1 ~ +1
    confidence: float  # 0 ~ 1
    key_sentence: str
    topic: str
    is_important: bool
    hawk_dove: Optional[str]  # 鹰派/鸽派/None
    hawk_dove_score: Optional[float]  # 正=鹰派，负=鸽派
    title_zh: Optional[str] = None  # 中文概括标题


def _detect_topic(text: str) -> str:
    t = text.lower()
    if any(k in t for k in ["fed", "powell", "rate", "联邦储备", "利率", "鲍威尔"]):
        return "Fed"
    if any(k in t for k in ["inflation", "cpi", "pce", "通胀"]):
        return "Inflation"
    if any(k in t for k in ["geopolitical", "war", "middle east", "地缘", "冲突"]):
        return "Geopolitical"
    if any(k in t for k in ["gold", "xau", "黄金"]):
        return "Gold"
    return "Other"


def _rule_based(title: str, content: str = "") -> SentimentResult:
    """关键词规则引擎（降级方案）。"""
    text = f"{title} {content}".lower()
    bull = sum(1 for k in BULL_KEYWORDS if k in text)
    bear = sum(1 for k in BEAR_KEYWORDS if k in text)

    if bull > bear:
        sentiment, label = "bullish", "利多"
        score = min(0.6, 0.2 * (bull - bear) + 0.2)
    elif bear > bull:
        sentiment, label = "bearish", "利空"
        score = max(-0.6, -(0.2 * (bear - bull) + 0.2))
    else:
        sentiment, label, score = "neutral", "中性", 0.0

    # 鹰鸽
    hawk = sum(1 for k in HAWK_KEYWORDS if k in text)
    dove = sum(1 for k in DOVE_KEYWORDS if k in text)
    hawk_dove = None
    hawk_dove_score = None
    if hawk > dove:
        hawk_dove, hawk_dove_score = "鹰派", min(0.5, 0.15 * (hawk - dove) + 0.1)
    elif dove > hawk:
        hawk_dove, hawk_dove_score = "鸽派", -min(0.5, 0.15 * (dove - hawk) + 0.1)

    is_important = any(
        k in text for k in ["powell", "fed", "rate decision", "鲍威尔", "美联储"]
    )
    topic = _detect_topic(text)
    title_zh = summarize_title(title, content, sentiment, topic)
    return SentimentResult(
        sentiment=sentiment,
        sentiment_label=label,
        sentiment_score=round(score, 3),
        confidence=0.6,  # 规则引擎固定置信度
        key_sentence=title,
        topic=topic,
        is_important=is_important,
        hawk_dove=hawk_dove,
        hawk_dove_score=round(hawk_dove_score, 3) if hawk_dove_score is not None else None,
        title_zh=title_zh,
    )


def _llm_analyze(title: str, content: str = "") -> Optional[SentimentResult]:
    """LangChain + OpenAI 情感分析。失败返回 None。"""
    if not settings.has_openai:
        return None
    try:
        from langchain_openai import ChatOpenAI
        from langchain_core.messages import HumanMessage, SystemMessage

        llm = ChatOpenAI(
            model=settings.openai_model,
            temperature=0,
            api_key=settings.openai_api_key,
            max_tokens=300,
        )
        sys = SystemMessage(
            content=(
                "你是黄金市场新闻分析助手。对新闻标题+摘要输出 JSON："
                '{"sentiment":"bullish|bearish|neutral","score":-1~1,'
                '"confidence":0~1,"key_sentence":"关键句(英文原文)",'
                '"topic":"Fed|Inflation|Geopolitical|Gold|Other",'
                '"hawk_dove":"鹰派|鸽派|null","hawk_dove_score":-0.5~0.5或null,'
                '"is_important":true|false,'
                '"title_zh":"不超过25字的中文概括标题，用中文提炼核心事实与关键数据、呼应关键句，'
                '不要使用看多/看空/利好黄金/利空黄金等单纯方向词"}。仅返回 JSON。'
            )
        )
        human = HumanMessage(content=f"标题: {title}\n摘要: {content}")
        resp = llm.invoke([sys, human])
        import json

        text = resp.content.strip()
        # 提取 JSON
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if not m:
            return None
        data = json.loads(m.group(0))
        sent = data.get("sentiment", "neutral")
        label = {"bullish": "利多", "bearish": "利空", "neutral": "中性"}.get(sent, "中性")
        hd = data.get("hawk_dove")
        if hd in ("null", "None", None):
            hd = None
        hds = data.get("hawk_dove_score")
        if hds in ("null", "None", None):
            hds = None
        title_zh = data.get("title_zh") or summarize_title(title, content, sent, data.get("topic", _detect_topic(title)))
        return SentimentResult(
            sentiment=sent,
            sentiment_label=label,
            sentiment_score=float(data.get("score", 0)),
            confidence=float(data.get("confidence", 0.7)),
            key_sentence=data.get("key_sentence", title),
            topic=data.get("topic", _detect_topic(title)),
            is_important=bool(data.get("is_important", False)),
            hawk_dove=hd,
            hawk_dove_score=float(hds) if hds is not None else None,
            title_zh=title_zh,
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("LLM 情感分析失败，降级规则引擎: %s", e)
        return None


def analyze_news(title: str, content: str = "") -> SentimentResult:
    """分析单条新闻。优先 LLM，失败降级规则引擎。"""
    result = _llm_analyze(title, content)
    if result is not None:
        return result
    return _rule_based(title, content)


def aggregate_sentiment(results: list[SentimentResult], window: int = 30) -> tuple[float, float]:
    """聚合最近 window 条新闻情感。

    返回 (sentiment_score 均值 [-1,1], hawk_dove_score 均值 [-0.5,0.5])。
    """
    if not results:
        return 0.0, 0.0
    recent = results[:window]
    sent_mean = sum(r.sentiment_score for r in recent) / len(recent)
    hd_scores = [r.hawk_dove_score for r in recent if r.hawk_dove_score is not None]
    hd_mean = sum(hd_scores) / len(hd_scores) if hd_scores else 0.0
    return round(sent_mean, 3), round(hd_mean, 3)


# ============================================================
# 以下为当前项目原有实现：情感分析结果落库器（C-1/C-2），向后兼容保留。
# main 后端仅提供 analyze_news / SentimentResult（读取用），落库仍走此处。
# ============================================================
from typing import Sequence

from sqlalchemy import select

from app.models.database import SessionLocal
from app.models.tables import News, Sentiment


class SentimentStorer:
    """情感结果落库器（C-1）。"""

    def store(self, db, pairs: Sequence) -> dict:
        """写入 sentiment 表。

        Args:
            db: SQLAlchemy Session
            pairs: list of (news_id: int, sentiment: SentimentResult-like)
                   sentiment 只需具备 sentiment_score / topic / confidence / key_sentence 属性
                   （兼容 news_scraper_llm.models.SentimentResult 与 app.core.sentiment.SentimentResult）

        Returns:
            {"inserted": int, "skipped": int, "ids": [int, ...]}
        """
        inserted = skipped = 0
        ids: list[int] = []

        for news_id, sent in pairs:
            if news_id is None:
                skipped += 1
                continue
            if db.execute(
                select(Sentiment.id).where(Sentiment.news_id == news_id)
            ).scalar_one_or_none() is not None:
                skipped += 1
                continue

            row = Sentiment(
                news_id=news_id,
                score=getattr(sent, "sentiment_score", None),
                topic=getattr(sent, "topic", None),
                confidence=getattr(sent, "confidence", None),
                key_sentence=getattr(sent, "key_sentence", None),
            )
            db.add(row)
            db.flush()
            inserted += 1
            ids.append(row.id)

        db.commit()
        return {"inserted": inserted, "skipped": skipped, "ids": ids}

    @staticmethod
    def has_sentiment_for_url(db, url: str | None) -> bool:
        """该新闻 URL 是否已有情感分析结果（用于跳过 LLM 调用）。"""
        if not url:
            return False
        stmt = (
            select(Sentiment.id)
            .join(News, Sentiment.news_id == News.id)
            .where(News.url == url)
            .limit(1)
        )
        return db.execute(stmt).scalar_one_or_none() is not None

    def select_for_analysis(self, db, raw_items: Sequence) -> list:
        """筛出尚未分析过（URL 未命中缓存）的新闻。"""
        return [
            it for it in raw_items
            if not self.has_sentiment_for_url(db, getattr(it, "url", None))
        ]
