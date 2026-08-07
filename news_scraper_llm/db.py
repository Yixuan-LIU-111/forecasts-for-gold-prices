"""
落库层（需求 2 数据表设计 + 需求 4 幂等落库）

复用项目统一分析库 data/gold_predictor.db（与 app 共用，SQLAlchemy 2.0）。
沿用了 app/models/database.py 对 SQLite 的适配：WAL + busy_timeout + 外键 pragma。

表结构：
- news（沿用 app 既有表，URL 唯一约束去重）：id / title / content / source / url / published_at / collected_at
- sentiment（在 app 既有字段基础上增量加列）：
    news_id          INT FK→news.id       新闻标识
    sentiment_label  VARCHAR(20)          情感倾向 positive/negative/neutral（新增）
    score            NUMERIC(4,3)         情感分值 -1~+1
    topic            VARCHAR(50)          主题
    confidence       NUMERIC(3,2)         置信度 0~1
    key_sentence     TEXT                 关键句
    model_version    VARCHAR(80)          模型版本（新增，如 qwen-turbo）
    sentiment_mode   VARCHAR(20)          分析模式 general/gold（新增）
    analyzed_at      DATETIME             分析时间（新增）
    created_at       DATETIME             入库审计

去重 / 幂等策略：
- news：按 url 唯一；url 为空时退化为 (source, title) 复合判定，避免重复建新闻行。
- sentiment：唯一索引 uq_sentiment_news_model_mode(news_id, model_version, sentiment_mode)
  → 同一新闻用同一模型+模式只保留一行，重跑=UPDATE 而非堆积（避免重复入库）。
- 落库前可用 select_unanalyzed() 筛除已分析 URL，跳过 LLM 调用（省成本，对应 C-2）。
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Iterable, Sequence

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    create_engine,
    event,
    func,
    select,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from .config import settings
from .models import RawNewsItem, SentimentResult

logger = logging.getLogger(__name__)


# ------------------ ORM 模型 ------------------

class Base(DeclarativeBase):
    """声明基类（对齐 app 的 SQLAlchemy 2.0 风格）。"""


class DbNews(Base):
    """新闻原始数据（与 app 的 news 表同名同结构，URL 唯一约束用于去重）。

    额外内联情感字段与 app.models.database.News 对齐，使前端 serialize_news
    无需 JOIN 即可直接读到真实情感（修复「真实新闻在前端显示成中性」的可见性 bug）。
    """

    __tablename__ = "news"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str | None] = mapped_column(String(100), nullable=True)
    url: Mapped[str | None] = mapped_column(Text, nullable=True, unique=True)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # —— 内联情感字段（与 app 的 News 表对齐，供前端直接读取，无需 JOIN）——
    # 取值约定：sentiment ∈ {bullish,bearish,neutral}（与前端渲染逻辑一致）；
    # sentiment_label ∈ {利多,利空,中性}；score 为 -1~+1 数值。
    sentiment: Mapped[str | None] = mapped_column(String(10), nullable=True)
    sentiment_label: Mapped[str | None] = mapped_column(String(10), nullable=True)
    sentiment_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    topic: Mapped[str | None] = mapped_column(String(50), nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    key_sentence: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_important: Mapped[bool] = mapped_column(Boolean, default=False)
    hawk_dove: Mapped[str | None] = mapped_column(String(10), nullable=True)
    hawk_dove_score: Mapped[float | None] = mapped_column(Float, nullable=True)


class DbSentiment(Base):
    """LLM 情感分析结果（在 app 既有 sentiment 表上增量扩展字段）。"""

    __tablename__ = "sentiment"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    news_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("news.id"), nullable=True)
    sentiment_label: Mapped[str | None] = mapped_column(String(20), nullable=True)
    score: Mapped[float | None] = mapped_column(Numeric(4, 3), nullable=True)
    topic: Mapped[str | None] = mapped_column(String(50), nullable=True)
    confidence: Mapped[float | None] = mapped_column(Numeric(3, 2), nullable=True)
    key_sentence: Mapped[str | None] = mapped_column(Text, nullable=True)
    # ---- 新增字段（由本包负责迁移建列）----
    model_version: Mapped[str | None] = mapped_column(String(80), nullable=True)
    sentiment_mode: Mapped[str | None] = mapped_column(String(20), nullable=True)
    analyzed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        # 幂等去重：同一新闻 + 同一模型 + 同一模式只允许一行；重跑即更新
        Index(
            "uq_sentiment_news_model_mode",
            "news_id",
            "model_version",
            "sentiment_mode",
            unique=True,
        ),
    )


# ------------------ 引擎与初始化 ------------------

_engine = None
_SessionLocal = None


def get_engine():
    """惰性创建引擎（按方言自适应，SQLite 开启 WAL/忙等待/外键）。"""
    global _engine, _SessionLocal
    if _engine is None:
        url = settings.database_url
        kw: dict = {"echo": settings.db_echo}
        if url.startswith("sqlite"):
            kw["connect_args"] = {"check_same_thread": False}
        _engine = create_engine(url, **kw)

        if url.startswith("sqlite") and ":memory:" not in url:
            @event.listens_for(_engine, "connect")
            def _set_sqlite_pragmas(dbapi_conn, _record):
                cur = dbapi_conn.cursor()
                cur.execute("PRAGMA journal_mode=WAL")
                cur.execute("PRAGMA busy_timeout=5000")
                cur.execute("PRAGMA foreign_keys=ON")
                cur.close()

        _SessionLocal = sessionmaker(bind=_engine, autoflush=False, autocommit=False)
    return _engine


# 增量迁移：确保 app 既有 sentiment 表拥有本包所需的新列（兼容性，不破坏 app 结构）
_NEW_SENTIMENT_COLUMNS = [
    ("sentiment_label", "VARCHAR(20)"),
    ("model_version", "VARCHAR(80)"),
    ("sentiment_mode", "VARCHAR(20)"),
    ("analyzed_at", "DATETIME"),
]

# 增量迁移：确保 news 表拥有与 app.News 对齐的内联情感列（前端直接读取，无需 JOIN）。
# 若 app 先建表则本步骤为 no-op；若本包先建表（独立运行）则补齐这些列，避免 app 读列报错。
_NEW_NEWS_COLUMNS = [
    ("sentiment", "VARCHAR(10)"),
    ("sentiment_label", "VARCHAR(10)"),
    ("sentiment_score", "FLOAT"),
    ("topic", "VARCHAR(50)"),
    ("confidence", "FLOAT"),
    ("key_sentence", "TEXT"),
    ("is_important", "BOOLEAN"),
    ("hawk_dove", "VARCHAR(10)"),
    ("hawk_dove_score", "FLOAT"),
]

# 本包情感标签（positive/negative/neutral）→ app 约定的内联列取值（bullish/bearish/neutral + 中文）
_LABEL_TO_APP = {
    "positive": ("bullish", "利多"),
    "negative": ("bearish", "利空"),
    "neutral": ("neutral", "中性"),
}


def _map_sentiment_label(label: str | None) -> tuple[str, str]:
    """把本包标签映射为 app 前端所需的 (sentiment, sentiment_label) 取值。"""
    return _LABEL_TO_APP.get((label or "neutral").lower(), ("neutral", "中性"))


def init_db() -> None:
    """建表（若不存在）+ 增量加列（sentiment / news 表新字段）+ 唯一索引。

    复用 app 已创建的 news/sentiment 表；本函数只确保「本包所需列与索引」存在，
    不会删除或修改 app 既有列。
    """
    engine = get_engine()
    Base.metadata.create_all(bind=engine)  # 仅建缺失的表；已存在的表不会被改动

    with engine.connect() as conn:
        # ---- sentiment 表新列 + 唯一索引 ----
        existing_sent = {
            row[1]
            for row in conn.execute(text("PRAGMA table_info(sentiment)")).fetchall()
        }
        for col, col_type in _NEW_SENTIMENT_COLUMNS:
            if col not in existing_sent:
                logger.info("迁移 sentiment 表：新增列 %s %s", col, col_type)
                conn.execute(text(
                    f"ALTER TABLE sentiment ADD COLUMN {col} {col_type}"
                ))
        conn.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_sentiment_news_model_mode "
            "ON sentiment(news_id, model_version, sentiment_mode)"
        ))

        # ---- news 表内联情感列（与 app.News 对齐）----
        existing_news = {
            row[1]
            for row in conn.execute(text("PRAGMA table_info(news)")).fetchall()
        }
        for col, col_type in _NEW_NEWS_COLUMNS:
            if col not in existing_news:
                logger.info("迁移 news 表：新增列 %s %s", col, col_type)
                conn.execute(text(
                    f"ALTER TABLE news ADD COLUMN {col} {col_type}"
                ))
        conn.commit()


def _parse_published_at(raw: str | None) -> datetime:
    """尽力把抓取到的原始发布时间字符串解析为 datetime；失败则回退当前 UTC 时间。"""
    if not raw:
        return datetime.utcnow()
    s = raw.strip().replace("Z", "+00:00")
    candidates = [
        lambda: datetime.fromisoformat(s),
        lambda: datetime.strptime(raw.strip(), "%Y-%m-%d %H:%M:%S"),
        lambda: datetime.strptime(raw.strip(), "%Y-%m-%d"),
        lambda: datetime.strptime(raw.strip(), "%a, %d %b %Y %H:%M:%S %z"),
        lambda: datetime.strptime(raw.strip(), "%b %d, %Y"),
    ]
    for fn in candidates:
        try:
            return fn()
        except Exception:
            continue
    return datetime.utcnow()


# ------------------ 幂等写入 ------------------

def _get_or_create_news(db, item: RawNewsItem) -> tuple[int, bool]:
    """新闻去重：按 url（空则 source+title）定位既有行，否则插入新行。返回 (news_id, inserted)。"""
    if item.url:
        existing = db.execute(
            select(DbNews).where(DbNews.url == item.url)
        ).scalar_one_or_none()
    else:
        existing = db.execute(
            select(DbNews).where(
                DbNews.url.is_(None),
                DbNews.source == item.source,
                DbNews.title == item.title,
            )
        ).scalar_one_or_none()

    if existing is not None:
        return existing.id, False

    row = DbNews(
        title=item.title,
        content=item.summary,
        source=item.source,
        url=item.url,
        published_at=_parse_published_at(item.published_at),
    )
    db.add(row)
    db.flush()
    return row.id, True


def _upsert_sentiment(db, news_id: int, sent: SentimentResult, model_version: str, mode: str) -> str:
    """情感幂等写入：同 (news_id, model_version, mode) 已存在则更新，否则插入。返回 'inserted'/'updated'。"""
    existing = db.execute(
        select(DbSentiment).where(
            DbSentiment.news_id == news_id,
            DbSentiment.model_version == model_version,
            DbSentiment.sentiment_mode == mode,
        )
    ).scalar_one_or_none()

    if existing is not None:
        existing.sentiment_label = sent.sentiment_label
        existing.score = sent.sentiment_score
        existing.topic = sent.topic
        existing.confidence = sent.confidence
        existing.key_sentence = sent.key_sentence
        existing.analyzed_at = datetime.utcnow()
        return "updated"

    row = DbSentiment(
        news_id=news_id,
        sentiment_label=sent.sentiment_label,
        score=sent.sentiment_score,
        topic=sent.topic,
        confidence=sent.confidence,
        key_sentence=sent.key_sentence,
        model_version=model_version,
        sentiment_mode=mode,
        analyzed_at=datetime.utcnow(),
    )
    db.add(row)
    return "inserted"


def persist(
    items: Iterable[tuple[RawNewsItem, SentimentResult, str]],
    mode: str,
) -> dict:
    """批量落库（需求 4：批量写入 + 幂等控制）。

    Args:
        items: (RawNewsItem, SentimentResult, model_version) 三元组可迭代对象
        mode:  本次分析模式（general/gold），参与幂等键

    Returns:
        统计字典：news_inserted / news_existing / sentiment_inserted /
                 sentiment_updated / failed
    """
    init_db()
    engine = get_engine()
    stats = {
        "news_inserted": 0,
        "news_existing": 0,
        "sentiment_inserted": 0,
        "sentiment_updated": 0,
        "failed": 0,
    }

    with _SessionLocal() as db:
        for raw, sent, model_version in items:
            mv = model_version or settings.openai_model
            try:
                news_id, inserted = _get_or_create_news(db, raw)
                if inserted:
                    stats["news_inserted"] += 1
                else:
                    stats["news_existing"] += 1

                result = _upsert_sentiment(db, news_id, sent, mv, mode)
                if result == "inserted":
                    stats["sentiment_inserted"] += 1
                else:
                    stats["sentiment_updated"] += 1

                # 回填 news 表内联情感列，使 app 前端无需 JOIN 即读到真实情感
                # （修复「真实新闻在前端显示成中性」的可见性 bug）。
                # 前端要求 news.sentiment ∈ {bullish,bearish,neutral}，故此处做标签映射。
                bull, zh = _map_sentiment_label(sent.sentiment_label)
                nrow = db.get(DbNews, news_id)
                if nrow is not None:
                    nrow.sentiment = bull
                    nrow.sentiment_label = zh
                    nrow.sentiment_score = sent.sentiment_score
                    nrow.topic = sent.topic
                    nrow.confidence = sent.confidence
                    nrow.key_sentence = sent.key_sentence
            except Exception as exc:  # 单条失败不影响其余；记录失败便于排查
                stats["failed"] += 1
                logger.error("落库失败 title=%r: %s", getattr(raw, "title", ""), exc)
        db.commit()

    logger.info("落库统计: %s", stats)
    return stats


# ------------------ 分析前筛选（缓存命中，对应 C-2）------------------

def select_unanalyzed(
    raw_items: Sequence[RawNewsItem],
    model_version: str,
    mode: str,
) -> list[RawNewsItem]:
    """筛出尚未分析过的新闻（跳过 LLM 调用，省成本）。

    判定口径：news 行 + sentiment(news_id, model_version, mode) 组合不存在。
    url 为空时退化为 (source, title) 复合判定。
    """
    init_db()
    engine = get_engine()
    out: list[RawNewsItem] = []
    with _SessionLocal() as db:
        for it in raw_items:
            if it.url:
                has = db.execute(
                    select(DbSentiment.id)
                    .join(DbNews, DbSentiment.news_id == DbNews.id)
                    .where(
                        DbNews.url == it.url,
                        DbSentiment.model_version == model_version,
                        DbSentiment.sentiment_mode == mode,
                    )
                ).scalar_one_or_none()
            else:
                has = db.execute(
                    select(DbSentiment.id)
                    .join(DbNews, DbSentiment.news_id == DbNews.id)
                    .where(
                        DbNews.url.is_(None),
                        DbNews.source == it.source,
                        DbNews.title == it.title,
                        DbSentiment.model_version == model_version,
                        DbSentiment.sentiment_mode == mode,
                    )
                ).scalar_one_or_none()
            if has is None:
                out.append(it)
    return out
