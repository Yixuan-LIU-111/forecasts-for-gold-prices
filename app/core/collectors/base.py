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
    """采集 XAU/USD 最新价格并写入 market_data 表（实时走势核心数据源）。

    - 使用共享的 store_market_data（按 (timestamp, symbol) upsert 去重），
      避免重复时间戳触发 IntegrityError 导致整批回滚、新数据写不进去。
    - 单点采集（fetch_latest）：实时任务每轮只需追加一个最新价，轻量且高频，
      配合采集器内的线程超时保护，保证永不挂死。
    - 写库后裁剪 XAUUSD 历史，防止长期运行下 market_data 无限膨胀
      （实时服务的资源清理，对应前端「避免内存泄漏」的同等后端约束）。
    """
    from app.core.collectors.adapters import GoldPriceCollector
    from app.core.data_collector import store_market_data
    import pandas as pd

    c = GoldPriceCollector()
    try:
        point = c.fetch_latest()
        if not point:
            logger.warning("采集金价失败：无可用数据源")
            return False
        ts, price, volume = point
        df = pd.DataFrame(
            [{"timestamp": ts, "symbol": "XAUUSD", "price": price, "volume": volume}]
        )
        n = store_market_data(db, df)
        if n > 0:
            _prune_xauusd(db, keep=6000)
        logger.info("采集金价成功：写入 %d 条（XAUUSD）", n)
        return n > 0
    except Exception as e:  # noqa: BLE001
        db.rollback()
        logger.warning("采集金价异常: %s", e)
        return False


def _prune_xauusd(db: Session, keep: int = 5000) -> None:
    """保留 XAUUSD 最近 keep 条，删除更早的历史，避免实时服务无限膨胀。

    仅在明显超出阈值时才删，避免无谓写库；保留阈值远大于前端最大展示窗口
    （7d≈672 点、48h≈5760 点），不影响任意时间范围的走势渲染。
    """
    from sqlalchemy import select, func, desc

    try:
        total = db.execute(
            select(func.count()).select_from(MarketData)
            .where(MarketData.symbol == "XAUUSD")
        ).scalar() or 0
        if total <= keep:
            return
        cutoff = db.execute(
            select(MarketData.timestamp)
            .where(MarketData.symbol == "XAUUSD")
            .order_by(desc(MarketData.timestamp))
            .limit(1).offset(keep - 1)
        ).scalar()
        if cutoff is None:
            return
        db.execute(
            MarketData.__table__.delete()
            .where(MarketData.symbol == "XAUUSD")
            .where(MarketData.timestamp < cutoff)
        )
        db.commit()
    except Exception as e:  # noqa: BLE001
        db.rollback()
        logger.warning("XAUUSD 历史裁剪失败（不影响本轮数据）: %s", e)
