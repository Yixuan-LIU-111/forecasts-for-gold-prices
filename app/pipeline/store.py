"""
落库模块：将 ScrapeRecord 校验后 upsert 写入 scraped_gold_prices。

- 复用 app.core.data_collector._dialect_insert 实现 SQLite / PostgreSQL 通用 upsert
  （SQLite 的 ON CONFLICT 依赖 models.py 中的真实唯一约束）
- 默认使用项目主库引擎（app.models.database.engine）；测试可注入独立引擎
- 设计对齐后端-dev「Service 层承载核心业务逻辑、入口层校验」：清洗/范围校验在此完成
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Iterable, Optional

from sqlalchemy import Engine
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.data_collector import _dialect_insert
from app.models.database import Base, engine as default_engine
from app.pipeline.models import ScrapedGoldPrice
from app.pipeline.scraper import ScrapeRecord

logger = logging.getLogger(__name__)


class GoldPriceStore:
    """黄金价格落库服务。"""

    def __init__(self, engine: Optional[Engine] = None) -> None:
        self.engine = engine or default_engine

    # —— Schema ——
    def ensure_table(self) -> None:
        """确保 scraped_gold_prices 表存在（仅建该表，不影响其它表）。"""
        Base.metadata.create_all(bind=self.engine, tables=[ScrapedGoldPrice.__table__])

    # —— 写入 ——
    def store_many(self, records: Iterable[ScrapeRecord], source: Optional[str] = None) -> int:
        """批量 upsert；返回尝试写入的行数（冲突行被忽略，不报错）。"""
        rows = [self._to_row(r, source) for r in records]
        rows = [r for r in rows if r is not None]
        if not rows:
            return 0
        with Session(self.engine) as db:
            stmt = _dialect_insert(ScrapedGoldPrice).values(rows)
            stmt = stmt.on_conflict_do_nothing(index_elements=["source", "symbol", "quote_date"])
            db.execute(stmt)
            db.commit()
        logger.info("upsert %d 行到 scraped_gold_prices", len(rows))
        return len(rows)

    # —— 查询（供测试与校验）——
    def count(self, source: Optional[str] = None) -> int:
        with Session(self.engine) as db:
            stmt = select(func.count()).select_from(ScrapedGoldPrice)
            if source:
                stmt = stmt.where(ScrapedGoldPrice.source == source)
            return int(db.scalar(stmt) or 0)

    def fetch_all(self) -> list[ScrapeRecord]:
        with Session(self.engine) as db:
            rows = db.scalars(select(ScrapedGoldPrice)).all()
            return [
                ScrapeRecord(
                    source=r.source, symbol=r.symbol, quote_date=r.quote_date,
                    open=r.open, high=r.high, low=r.low, close=r.close,
                    volume=r.volume, currency=r.currency,
                )
                for r in rows
            ]

    # —— 内部 ——
    @staticmethod
    def _to_row(rec: ScrapeRecord, source: Optional[str]) -> Optional[dict]:
        if not (1.0 <= rec.close <= 100_000.0):
            return None
        return {
            "source": source or rec.source,
            "symbol": rec.symbol,
            "quote_date": rec.quote_date,
            "open": rec.open,
            "high": rec.high,
            "low": rec.low,
            "close": rec.close,
            "volume": rec.volume,
            "currency": rec.currency,
            "scraped_at": datetime.now(timezone.utc),
        }
