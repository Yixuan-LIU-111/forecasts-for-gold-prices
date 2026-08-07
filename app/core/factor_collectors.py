"""存量因子 scraper 接入统一接口 + 写库（B-7，对齐 项目方案V1.0 §11.1 DataCollector）。

将 6 个独立 CLI 爬虫封装为 DataCollector 子类，落到 SQLite / PostgreSQL（方言自适应）：
- 数值因子（DXY / VIX / TIPS10Y / GPR / EPU）→ market_data 表
- 财经日历（investing_calendar）→ economic_calendar 表（事件型，独立成表）

设计要点：
- 各 scraper 以「裸名模块」(config/scraper/utils) 组织，彼此同名会冲突；
  故用 _load_scraper_module() 在隔离的 sys.path 下逐个加载，避免互相污染。
- fetch() 真正触发网络抓取；_normalize() 为纯函数，便于无网环境下单测。
- 数值因子统一经 store_market_data() upsert，按 (timestamp, symbol) 去重。
"""
from __future__ import annotations

import importlib.util
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import pandas as pd
from sqlalchemy.orm import Session

from app.core.data_collector import DataCollector, store_market_data, _dialect_insert
from app.models.tables import EconomicCalendar, MarketData

_SCRAPER_ROOT = Path(__file__).resolve().parents[2]  # 仓库根目录


# --------------------------------------------------------------------------- #
# scraper 隔离加载（解决裸名模块跨 scraper 冲突）
# --------------------------------------------------------------------------- #
def _load_scraper_module(dir_name: str, mod_name: str):
    """在隔离 sys.path 下加载某 scraper 的子模块（config/scraper/...）。

    每次加载前清除可能残留的同名裸模块，确保 `from config import ...`
    解析到当前 scraper 目录，而非上一次加载的 scraper。
    """
    for stale in ("config", "scraper", "storage", "utils", "parser"):
        sys.modules.pop(stale, None)
    scraper_dir = _SCRAPER_ROOT / dir_name
    sys.path.insert(0, str(scraper_dir))
    try:
        spec = importlib.util.spec_from_file_location(
            mod_name, scraper_dir / f"{mod_name}.py"
        )
        module = importlib.util.module_from_spec(spec)
        sys.modules[mod_name] = module
        spec.loader.exec_module(module)
    finally:
        sys.path.pop(0)
    return module


def _parse_dt(date_str: Optional[str], time_str: Optional[str] = None) -> Optional[datetime]:
    """把日期/时间字符串解析为（naive）datetime；失败返回 None。"""
    if not date_str:
        return None
    raw = str(date_str)
    if time_str:
        raw = f"{raw} {time_str}"
    try:
        from dateutil.parser import parse as _du_parse

        return _du_parse(raw)
    except Exception:
        return None


def _tz_aware(dt: Optional[datetime]) -> Optional[datetime]:
    if isinstance(dt, datetime) and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


# --------------------------------------------------------------------------- #
# 数值因子采集器（落 market_data）
# --------------------------------------------------------------------------- #
class DXYCollector(DataCollector):
    """美元指数 DXY（新浪财经），symbol=DXY。"""

    SYMBOL = "DXY"

    def fetch(self) -> pd.DataFrame:
        mod = _load_scraper_module("dxy_scraper", "scraper")
        data = mod.scrape_dxy()
        return self._normalize(data)

    @staticmethod
    def _normalize(data: Optional[dict]) -> pd.DataFrame:
        if not data or data.get("current_price") is None:
            return pd.DataFrame(columns=["timestamp", "symbol", "price", "volume"])
        ts = _tz_aware(_parse_dt(data.get("date"), data.get("time"))) or datetime.now(timezone.utc)
        return pd.DataFrame(
            [{"timestamp": ts, "symbol": DXYCollector.SYMBOL,
              "price": float(data["current_price"]), "volume": None}]
        )


class VIXCollector(DataCollector):
    """VIX 恐慌指数（CBOE），symbol=VIX。"""

    SYMBOL = "VIX"

    def fetch(self) -> pd.DataFrame:
        mod = _load_scraper_module("vix_scraper", "scraper")
        scraper = mod.VIXScraper(headless=True)
        data = scraper.fetch_vix_data()
        return self._normalize(data)

    @staticmethod
    def _normalize(data: Optional[dict]) -> pd.DataFrame:
        if not data or data.get("vix_spot_price") is None:
            return pd.DataFrame(columns=["timestamp", "symbol", "price", "volume"])
        ts = datetime.now(timezone.utc)
        return pd.DataFrame(
            [{"timestamp": ts, "symbol": VIXCollector.SYMBOL,
              "price": float(data["vix_spot_price"]), "volume": None}]
        )


class TIPSCollector(DataCollector):
    """TIPS 10 年期实际收益率（FRED DFII10），symbol=TIPS10Y，支持历史回填。"""

    SYMBOL = "TIPS10Y"

    def fetch(self) -> pd.DataFrame:
        mod = _load_scraper_module("dfii10_scraper", "scraper")
        data = mod.scrape_dfii10()
        return self._normalize(data)

    @staticmethod
    def _normalize(data: Optional[dict]) -> pd.DataFrame:
        if not data:
            return pd.DataFrame(columns=["timestamp", "symbol", "price", "volume"])
        rows = []
        for r in data.get("recent_data", []) or []:
            ts = _tz_aware(_parse_dt(r.get("date")))
            if ts is None or r.get("value") is None:
                continue
            rows.append({"timestamp": ts, "symbol": TIPSCollector.SYMBOL,
                         "price": float(r["value"]), "volume": None})
        if not rows and data.get("latest_value") is not None:
            ts = _tz_aware(_parse_dt(data.get("latest_date"))) or datetime.now(timezone.utc)
            rows.append({"timestamp": ts, "symbol": TIPSCollector.SYMBOL,
                         "price": float(data["latest_value"]), "volume": None})
        return pd.DataFrame(rows, columns=["timestamp", "symbol", "price", "volume"])


class GPRCollector(DataCollector):
    """地缘政治风险指数 GPR（日度 gprd），symbol=GPR。"""

    SYMBOL = "GPR"

    def fetch(self) -> pd.DataFrame:
        mod = _load_scraper_module("gpr_scraper", "scraper")
        data = mod.scrape_gpr()
        return self._normalize(data)

    @staticmethod
    def _normalize(data: Optional[dict]) -> pd.DataFrame:
        if not data or data.get("gprd") is None:
            return pd.DataFrame(columns=["timestamp", "symbol", "price", "volume"])
        ts = _tz_aware(_parse_dt(data.get("date"))) or datetime.now(timezone.utc)
        return pd.DataFrame(
            [{"timestamp": ts, "symbol": GPRCollector.SYMBOL,
              "price": float(data["gprd"]), "volume": None}]
        )


class EPUCollector(DataCollector):
    """美国经济政策不确定性指数 EPU（日度），symbol=EPU，支持历史回填。"""

    SYMBOL = "EPU"

    def fetch(self) -> pd.DataFrame:
        mod = _load_scraper_module("epu_scraper", "scraper")
        data = mod.scrape_epu()
        return self._normalize(data)

    @staticmethod
    def _normalize(data: Optional[dict]) -> pd.DataFrame:
        if not data:
            return pd.DataFrame(columns=["timestamp", "symbol", "price", "volume"])
        rows = []
        for r in data.get("recent_data", []) or []:
            ts = _tz_aware(_parse_dt(r.get("date")))
            if ts is None or r.get("value") is None:
                continue
            rows.append({"timestamp": ts, "symbol": EPUCollector.SYMBOL,
                         "price": float(r["value"]), "volume": None})
        if not rows and data.get("latest_value") is not None:
            ts = _tz_aware(_parse_dt(data.get("latest_date"))) or datetime.now(timezone.utc)
            rows.append({"timestamp": ts, "symbol": EPUCollector.SYMBOL,
                         "price": float(data["latest_value"]), "volume": None})
        return pd.DataFrame(rows, columns=["timestamp", "symbol", "price", "volume"])


# --------------------------------------------------------------------------- #
# 财经日历采集器（落 economic_calendar 表）
# --------------------------------------------------------------------------- #
class CalendarCollector(DataCollector):
    """Investing.com 财经日历（高重要性事件），结果落 economic_calendar 表。"""

    def fetch(self) -> pd.DataFrame:
        mod = _load_scraper_module("investing_calendar_scraper", "scraper")
        from parser import parse_calendar, filter_events  # 同目录裸模块

        html = mod.fetch_calendar_html()
        if html is None:
            return pd.DataFrame(columns=self._cols())
        events = filter_events(parse_calendar(html))
        return self._normalize(events)

    @staticmethod
    def _cols() -> list[str]:
        return ["event_date", "time", "currency", "event",
                "importance", "actual", "forecast", "previous"]

    @staticmethod
    def _normalize(events: Optional[list[dict]]) -> pd.DataFrame:
        if not events:
            return pd.DataFrame(columns=CalendarCollector._cols())
        rows = []
        for e in events:
            ts = _tz_aware(_parse_dt(e.get("date"), e.get("time"))) or datetime.now(timezone.utc)
            rows.append({
                "event_date": ts,
                "time": e.get("time"),
                "currency": e.get("currency"),
                "event": e.get("event"),
                "importance": e.get("importance"),
                "actual": str(e.get("actual")) if e.get("actual") is not None else None,
                "forecast": str(e.get("forecast")) if e.get("forecast") is not None else None,
                "previous": str(e.get("previous")) if e.get("previous") is not None else None,
            })
        return pd.DataFrame(rows, columns=CalendarCollector._cols())

    def store(self, db: Session, df: pd.DataFrame) -> int:
        """把日历事件写入 economic_calendar 表（按 event_date+currency+event 去重）。"""
        if df is None or df.empty:
            return 0
        records = df.where(pd.notna(df), None).to_dict(orient="records")
        stmt = _dialect_insert(EconomicCalendar).values(records)
        stmt = stmt.on_conflict_do_nothing(
            index_elements=["event_date", "currency", "event"]
        )
        db.execute(stmt)
        db.commit()
        return len(records)

    async def collect_and_store(self, db: Session) -> int:
        df = await self.fetch()
        return self.store(db, df)


# --------------------------------------------------------------------------- #
# 便捷聚合：一次跑全量因子采集并写库（供 B-8 bootstrap 复用）
# --------------------------------------------------------------------------- #
NUMERIC_COLLECTORS = [DXYCollector, VIXCollector, TIPSCollector, GPRCollector, EPUCollector]


def collect_all_factors(db: Session) -> dict[str, int]:
    """运行全部数值因子采集器 + 日历采集器，写库并返回各采集器写入行数。

    数值因子采集器 fetch() 为同步；日历采集器 fetch() 为异步，用 asyncio.run 驱动。
    单源失败不影响其余源（写入失败计 -1）。
    """
    import asyncio
    import logging

    logger = logging.getLogger(__name__)
    summary: dict[str, int] = {}
    for cls in NUMERIC_COLLECTORS:
        try:
            c = cls()
            df = c.fetch()
            summary[c.SYMBOL] = store_market_data(db, df)
        except Exception as exc:  # 单源失败不影响其余
            summary[getattr(cls, "SYMBOL", cls.__name__)] = -1
            logger.warning("因子采集失败 %s: %s", cls.__name__, exc)
    try:
        cal = CalendarCollector()
        df = asyncio.run(cal.fetch())
        summary["CALENDAR"] = cal.store(db, df)
    except Exception as exc:
        summary["CALENDAR"] = -1
        logger.warning("日历采集失败: %s", exc)
    return summary
