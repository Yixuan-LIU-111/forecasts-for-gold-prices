"""
爬虫落库表（ScrapedGoldPrice）。

- 与 app.models.database.Base 同源，init_db() 一并建表
- 唯一约束 (source, symbol, quote_date) 作为 SQLite / PostgreSQL 通用 upsert 的冲突目标
- 类型采用项目既定写法：Integer 自增主键、Float 价格、Date 日期、String 短文本
"""
from datetime import date, datetime

from sqlalchemy import DateTime, Date, Float, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.database import Base


class ScrapedGoldPrice(Base):
    """从页面抓取的黄金价格历史记录。"""

    __tablename__ = "scraped_gold_prices"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String(120), nullable=False)       # 数据来源标识
    symbol: Mapped[str] = mapped_column(String(20), nullable=False, default="XAU/USD")
    quote_date: Mapped[date] = mapped_column(Date, nullable=False)         # 行情日期
    open: Mapped[float | None] = mapped_column(Float, nullable=True)
    high: Mapped[float | None] = mapped_column(Float, nullable=True)
    low: Mapped[float | None] = mapped_column(Float, nullable=True)
    close: Mapped[float] = mapped_column(Float, nullable=False)            # 收盘价（必填）
    volume: Mapped[float | None] = mapped_column(Float, nullable=True)
    currency: Mapped[str] = mapped_column(String(10), nullable=False, default="USD")
    scraped_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        # SQLite 的 ON CONFLICT 需要真实唯一约束；PG 同源约束保证幂等
        UniqueConstraint("source", "symbol", "quote_date", name="uq_scraped_src_sym_date"),
    )
