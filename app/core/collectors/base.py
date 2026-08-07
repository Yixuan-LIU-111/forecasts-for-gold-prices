"""数据采集器抽象基类与统一调度入口。"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import pandas as pd
from sqlalchemy.orm import Session

from app.models.database import FactorData, MarketData

logger = logging.getLogger(__name__)


@dataclass
class CollectorResult:
    """采集器标准化输出。"""

    indicator_code: str
    indicator_name: str
    category: str
    value: float
    change: Optional[float] = None
    change_pct: Optional[float] = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    source: str = ""
    source_url: str = ""
    update_frequency: str = "实时"
    realtime_inference: bool = True
    value_type: str = "原始值"
    raw_data: Optional[dict] = None
    anti_crawl_flag: bool = False
    quality_score: float = 1.0


class DataCollector(ABC):
    """采集器抽象基类。"""

    indicator_code: str = ""
    indicator_name: str = ""
    category: str = ""
    update_frequency: str = "实时"
    realtime_inference: bool = True

    @abstractmethod
    def fetch(self) -> Optional[CollectorResult]:
        """采集最新数据，失败返回 None。"""
        ...

    def to_factor_row(self, result: CollectorResult) -> FactorData:
        """转为 FactorData ORM 对象。"""
        return FactorData(
            indicator_code=result.indicator_code,
            indicator_name=result.indicator_name,
            category=result.category,
            timestamp=result.timestamp,
            value=result.value,
            value_type=result.value_type,
            change=result.change,
            change_pct=result.change_pct,
            source=result.source,
            source_url=result.source_url,
            update_frequency=result.update_frequency,
            realtime_inference=result.realtime_inference,
            anti_crawl_flag=result.anti_crawl_flag,
            quality_score=result.quality_score,
            raw_data=result.raw_data,
        )


def collect_all_factors(db: Session) -> dict:
    """运行所有因子采集器并写入数据库。

    返回 {indicator_code: success} 摘要。爬虫可能因缺 Playwright/网络失败，
    失败时跳过，系统继续使用已有数据（首次启动由 seed 模块引导）。
    """
    from app.core.collectors.adapters import (
        DxyCollector,
        VixCollector,
        TipsCollector,
        GprCollector,
    )

    collectors = [DxyCollector(), VixCollector(), TipsCollector(), GprCollector()]
    summary: dict = {}
    for c in collectors:
        code = c.indicator_code
        try:
            result = c.fetch()
            if result is None:
                summary[code] = False
                logger.warning("采集 %s 失败（返回 None），跳过", code)
                continue
            db.add(c.to_factor_row(result))
            db.commit()
            summary[code] = True
            logger.info("采集 %s 成功: value=%s", code, result.value)
        except Exception as e:  # noqa: BLE001
            db.rollback()
            summary[code] = False
            logger.warning("采集 %s 异常: %s", code, e)
    return summary


def collect_gold_price(db: Session) -> bool:
    """采集 XAU/USD 价格并写入 market_data 表。"""
    from app.core.collectors.adapters import GoldPriceCollector

    c = GoldPriceCollector()
    try:
        prices = c.fetch_series()
        if not prices:
            return False
        for ts, price, volume in prices:
            db.add(
                MarketData(
                    timestamp=ts, symbol="XAUUSD", price=price, volume=volume
                )
            )
        db.commit()
        return True
    except Exception as e:  # noqa: BLE001
        db.rollback()
        logger.warning("采集金价异常: %s", e)
        return False
