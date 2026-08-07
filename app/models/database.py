"""
数据库初始化与连接管理（合并当前项目与 forecasts-for-gold-prices-main 后端）。

- 引擎：SQLAlchemy 2.0；按 DATABASE_URL 方言自适应
    * SQLite（文件型）：无连接池；允许跨线程（check_same_thread=False）；
      连接事件挂 WAL + busy_timeout + foreign_keys pragma 提升并发并避免锁错误
    * PostgreSQL：真实连接池 + 自动重连（pool_pre_ping）
- ORM 表模型（合并两分支的 schema，取并集以避免破坏任一侧代码）：
    * market_data        —— 两分支共有（价格序列）
    * factor_data         —— main 后端：6 因子统一标准化存储
    * news                —— 合并：当前基础字段 + main 的情感/鹰鸽内联字段
    * sentiment           —— 当前项目：独立的 LLM 情感分析表（外键 news）
    * signal / signals    —— 合并：main 的 Signal（含 attribution 等）+ 兼容别名 Signals
    * hawk_dove_events    —— 合并：main 的 HawkDoveEvent（date / news_id）
    * backtest_results    —— 合并：main 的 BacktestResult + 兼容别名 BacktestResults
    * economic_calendar   —— 当前项目：财经日历事件
- init_db() 建表；get_db() 供 FastAPI 依赖注入请求级会话；test_connection() 供健康检查。
"""
from __future__ import annotations

from collections.abc import Generator
from datetime import date, datetime

import uuid
from typing import Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    create_engine,
    event,
    func,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import settings


class Base(DeclarativeBase):
    """所有 ORM 模型的声明基类（SQLAlchemy 2.0 风格）。"""


# ============================================================
# 市场价格序列（两分支共有；采用当前项目的数值精度与唯一约束）
# ============================================================
class MarketData(Base):
    __tablename__ = "market_data"

    id = Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    timestamp = Column(DateTime(timezone=True), nullable=False, index=True)
    symbol = Column(String(20), nullable=False)  # GC=F, DX-Y.NYB, ^VIX, ^IRX
    price = Column(Numeric(12, 4))
    volume = Column(BigInteger().with_variant(Integer, "sqlite"))
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("idx_market_data_ts_sym", "timestamp", "symbol"),
        UniqueConstraint("timestamp", "symbol", name="uq_market_data_ts_sym"),
    )


# ============================================================
# 因子数据（main 后端：6 因子 + 扩展因子，统一标准化存储）
# ============================================================
class FactorData(Base):
    __tablename__ = "factor_data"

    id = Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    indicator_code = Column(String(20), nullable=False)  # DXY/TIPS10Y/VIX/GPR/...
    indicator_name = Column(String(50))
    category = Column(String(20))  # 地缘政治/美国经济/佐证表象/衍生
    timestamp = Column(DateTime(timezone=True), nullable=False, index=True)
    value = Column(Float)
    value_type = Column(String(20))  # 原始值/收益率/变化率/情感得分
    change = Column(Float)  # 变化值
    change_pct = Column(Float)  # 变化率 %
    source = Column(String(50))  # FRED/CBOE/新浪财经/LLM 分析
    source_url = Column(Text)
    update_frequency = Column(String(20))  # 实时/日频/周度/月度
    realtime_inference = Column(Boolean, default=False)
    ffill_flag = Column(Boolean, default=False)
    anti_crawl_flag = Column(Boolean, default=False)
    quality_score = Column(Float, default=1.0)
    raw_data = Column(JSON)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("idx_factor_ts_code", "timestamp", "indicator_code"),
    )


# ============================================================
# 新闻（合并：当前基础字段 + main 的情感/鹰鸽内联字段）
# ============================================================
class News(Base):
    __tablename__ = "news"

    id = Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    title = Column(Text, nullable=False)          # 原始标题（英文原文或已有中文）
    title_zh = Column(Text, nullable=True)        # 中文概括标题，用于前端展示
    content = Column(Text)
    source = Column(String(100))
    url = Column(Text, unique=True)  # 去重
    published_at = Column(DateTime(timezone=True), nullable=False, index=True)
    collected_at = Column(DateTime(timezone=True), server_default=func.now())
    # —— main 内联的情感与鹰鸽字段（LLM 分析后回填）——
    sentiment = Column(String(10))  # bullish/bearish/neutral
    sentiment_label = Column(String(10))  # 利多/利空/中性
    sentiment_score = Column(Float)  # -1.000 ~ +1.000
    topic = Column(String(50))  # Fed, Inflation, Geopolitical
    confidence = Column(Float)  # 0.00 ~ 1.00
    key_sentence = Column(Text)
    is_important = Column(Boolean, default=False)
    hawk_dove = Column(String(10))  # 鹰派/鸽派/NULL
    hawk_dove_score = Column(Float)  # 正=鹰派，负=鸽派


# ============================================================
# 情感分析结果（当前项目：独立的 LLM 情感分析表，外键关联 news）
# ============================================================
class Sentiment(Base):
    __tablename__ = "sentiment"

    id = Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    news_id = Column(BigInteger().with_variant(Integer, "sqlite"),
                     ForeignKey("news.id"), nullable=True)
    score = Column(Numeric(4, 3))  # -1.000 ~ +1.000
    topic = Column(String(50))  # Fed, Inflation...
    confidence = Column(Numeric(3, 2))  # 0.00 ~ 1.00
    key_sentence = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


# ============================================================
# 信号（合并：main 的 Signal + 兼容当前项目的 factors 列；别名 Signals）
# ============================================================
class Signal(Base):
    __tablename__ = "signals"

    id = Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    timestamp = Column(DateTime(timezone=True), nullable=False, index=True)
    direction = Column(String(10))  # 看涨/看跌/观望
    direction_en = Column(String(10))  # bullish/bearish/neutral
    probability = Column(Float)  # 0.000 ~ 1.000
    strength = Column(Integer)  # 0 ~ 100
    position = Column(String(10))  # 重仓/中仓/轻仓/观望
    position_pct = Column(Integer)  # 0 ~ 100
    bull_bear_score = Column(Integer)  # 0 ~ 100
    confidence = Column(String(4))  # 高/中/低
    confidence_value = Column(Integer)  # 0 ~ 100
    model = Column(String(50))  # LightGBM+XGBoost 加权
    attribution = Column(JSON)  # 6 因子归因数组（main）
    factors = Column(JSON)  # 因子归因（当前项目旧字段，保留兼容）
    news_refs = Column(JSON)  # 新闻来源引用
    stop_loss = Column(Float)
    take_profit = Column(Float)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


# 兼容别名：当前项目代码 `from app.models.tables import Signals`
Signals = Signal


# ============================================================
# 鹰鸽事件（合并：main 的 HawkDoveEvent，date / news_id）
# ============================================================
class HawkDoveEvent(Base):
    __tablename__ = "hawk_dove_events"

    id = Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    date = Column(Date, nullable=False, index=True)
    speaker = Column(String(50))
    score = Column(Float)  # 正=鸽派利好，负=鹰派利空
    type = Column(String(10))  # dove/hawk
    label = Column(String(10))  # 鸽派/鹰派
    summary = Column(Text)
    news_id = Column(BigInteger().with_variant(Integer, "sqlite"),
                     ForeignKey("news.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


# ============================================================
# 回测结果（合并：main 的 BacktestResult + 兼容别名 BacktestResults）
# ============================================================
class BacktestResult(Base):
    __tablename__ = "backtest_results"

    id = Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    run_id = Column(String(36), nullable=False, default=lambda: str(uuid.uuid4()))
    start_date = Column(Date)
    end_date = Column(Date)
    summary = Column(JSON)  # 收益率、夏普、回撤、胜率、盈亏比等
    accuracy = Column(JSON)  # 7d/30d/分方向准确率
    equity_curve = Column(JSON)  # 收益曲线
    trade_details = Column(JSON)  # 逐笔交易明细
    pnl_distribution = Column(JSON)  # 盈亏分布
    params = Column(JSON)  # 回测参数
    created_at = Column(DateTime(timezone=True), server_default=func.now())


# 兼容别名：当前项目代码 `from app.models.tables import BacktestResults`
BacktestResults = BacktestResult


# ============================================================
# 财经日历事件（当前项目：来源 investing_calendar_scraper）
# ============================================================
class EconomicCalendar(Base):
    __tablename__ = "economic_calendar"

    id = Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    event_date = Column(DateTime(timezone=True), nullable=False)
    time = Column(String(10))
    currency = Column(String(10))
    event = Column(Text)
    importance = Column(String(10))
    actual = Column(String(50))
    forecast = Column(String(50))
    previous = Column(String(50))
    scraped_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("idx_calendar_date", "event_date"),
        UniqueConstraint("event_date", "currency", "event", name="uq_calendar"),
    )


# ============================================================
# 数据源注册表（registry：各指标对应的真实采集源）
# ============================================================
class DataSource(Base):
    __tablename__ = "data_sources"

    id = Column(Integer, primary_key=True, autoincrement=True)
    indicator_code = Column(String(32), unique=True, nullable=False, index=True)
    indicator_name = Column(String(64), nullable=False)
    source_name = Column(String(128), nullable=False)
    source_url = Column(String(256), nullable=True)
    update_frequency = Column(String(32), nullable=False, default="实时")
    realtime = Column(Boolean, default=True)
    description = Column(Text, nullable=True)


# ============================================================
# 引擎与会话
# ============================================================
def _make_engine():
    """按 DATABASE_URL 方言创建引擎。

    - PostgreSQL：使用真实连接池 + 自动重连（pool_pre_ping）。
    - SQLite：无连接池概念；文件型需允许跨线程（check_same_thread=False）。
    """
    url = settings.database_url
    kw: dict = {"echo": settings.db_echo}
    if url.startswith("sqlite"):
        kw["connect_args"] = {"check_same_thread": False}
    else:
        kw.update(
            pool_size=settings.db_pool_size,
            max_overflow=settings.db_max_overflow,
            pool_timeout=settings.db_pool_timeout,
            pool_recycle=settings.db_pool_recycle,
            pool_pre_ping=True,
        )
    return create_engine(url, **kw)
    url = settings.database_url
    kw: dict = {"echo": settings.db_echo}
    if url.startswith("sqlite"):
        kw["connect_args"] = {"check_same_thread": False}
    else:
        kw.update(
            pool_size=settings.db_pool_size,
            max_overflow=settings.db_max_overflow,
            pool_timeout=settings.db_pool_timeout,
            pool_recycle=settings.db_pool_recycle,
            pool_pre_ping=True,
        )
    return create_engine(url, **kw)


engine = _make_engine()


# 文件型 SQLite：开启 WAL + 忙等待 + 外键，提升读写并发并避免 "database is locked"
if settings.database_url.startswith("sqlite") and ":memory:" not in settings.database_url:
    @event.listens_for(engine, "connect")
    def _set_sqlite_pragmas(dbapi_conn, _conn_record):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA busy_timeout=5000")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

# 会话工厂
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def init_db() -> None:
    """按 ORM 元数据创建全部表（合并后的 8 张表）。"""
    Base.metadata.create_all(bind=engine)


def get_db() -> Generator[Session, None, None]:
    """FastAPI 依赖：提供请求级数据库会话，结束时自动关闭。"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def test_connection() -> bool:
    """探测数据库连通性，返回 True 表示可成功执行查询。"""
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    return True
