"""
数据采集层（对齐 项目方案V1.0 §11.1 接口 + 差距分析 B-3 / B-4）

- DataCollector: 采集器抽象基类，定义 async fetch() -> pd.DataFrame
- YFinanceCollector: 价格采集实现（GC=F / DX-Y.NYB / ^VIX / ^IRX），
  分钟级数据 upsert 写入 market_data 表（按 timestamp+symbol 去重）
"""
import asyncio
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Iterable

import pandas as pd
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.config import settings
from app.models.tables import MarketData


def _dialect_insert(table):
    """按 DATABASE_URL 方言返回 insert 构造器（PG / SQLite 通用）。

    两者 API 一致，均支持 .values(...).on_conflict_do_nothing(index_elements=...)。
    SQLite 的 ON CONFLICT 要求存在真实唯一约束（见 tables.py 的 UniqueConstraint）。
    """
    if settings.DATABASE_URL.startswith("sqlite"):
        return sqlite_insert(table)
    return pg_insert(table)

# yfinance 在 fetch 内惰性导入，避免未安装时阻塞模块导入
DEFAULT_SYMBOLS = ("GC=F", "DX-Y.NYB", "^VIX", "^IRX")
DEFAULT_INTERVAL = "5m"   # 5 分钟 bar（D-1 建议；1m 仅 7 天历史，见风险 R2）
DEFAULT_PERIOD = "60d"    # 5m 约 60 天回溯（受 R2 限制）


class DataCollector(ABC):
    """采集器抽象基类（§11.1）。

    子类实现 fetch()，返回统一列：[timestamp, symbol, price, volume] 的 DataFrame。
    """

    @abstractmethod
    async def fetch(self) -> pd.DataFrame:
        """拉取最新数据。"""
        raise NotImplementedError


class YFinanceCollector(DataCollector):
    """yfinance 价格采集器，结果落库 market_data（B-4）。"""

    def __init__(
        self,
        symbols: Iterable[str] = DEFAULT_SYMBOLS,
        interval: str = DEFAULT_INTERVAL,
        period: str = DEFAULT_PERIOD,
        proxy: str | None = None,
    ) -> None:
        self.symbols = list(symbols)
        self.interval = interval
        self.period = period
        self.proxy = proxy

    async def fetch(self) -> pd.DataFrame:
        """下载分钟级行情并整理为长表。

        yfinance 为同步阻塞调用，用 asyncio.to_thread 避免阻塞事件循环。
        """
        import yfinance as yf

        raw = await asyncio.to_thread(
            yf.download,
            self.symbols,
            interval=self.interval,
            period=self.period,
            group_by="ticker",
            auto_adjust=False,
            progress=False,
            proxy=self.proxy,
        )
        return self._reshape(raw)

    @staticmethod
    def _reshape(raw: pd.DataFrame) -> pd.DataFrame:
        """将 yfinance 多标的面板整理为长表 [timestamp, symbol, price, volume]。"""
        rows: list[dict] = []
        if isinstance(raw.columns, pd.MultiIndex):
            for symbol in raw.columns.get_level_values(1).unique():
                sub = raw.xs(symbol, axis=1, level=1)
                for ts, row in sub.iterrows():
                    rows.append(
                        {
                            "timestamp": ts,
                            "symbol": symbol,
                            "price": float(row["Close"]) if pd.notna(row.get("Close")) else None,
                            "volume": int(row["Volume"]) if pd.notna(row.get("Volume")) else None,
                        }
                    )
        else:
            # 单标的：普通 DataFrame，列名无 symbol 层级
            for ts, row in raw.iterrows():
                rows.append(
                    {
                        "timestamp": ts,
                        "symbol": "UNKNOWN",
                        "price": float(row["Close"]) if pd.notna(row.get("Close")) else None,
                        "volume": int(row["Volume"]) if pd.notna(row.get("Volume")) else None,
                    }
                )
        return pd.DataFrame(rows)

    def store(self, db: Session, df: pd.DataFrame) -> int:
        """将采集结果 upsert 写入 market_data（按 timestamp+symbol 去重）。

        委托给模块级 store_market_data，与因子采集器共用同一写库逻辑。
        返回尝试写入的行数（冲突行被忽略，不报错）。
        """
        return store_market_data(db, df)

    async def collect_and_store(self, db: Session) -> int:
        """一次完整动作：fetch → store，返回写入行数。"""
        df = await self.fetch()
        return self.store(db, df)


def store_market_data(db: Session, df: pd.DataFrame) -> int:
    """把 [timestamp, symbol, price, volume] 长表 upsert 写入 market_data。

    统一供 YFinanceCollector 与所有因子采集器（B-7）复用。
    - 按 (timestamp, symbol) 去重（ON CONFLICT DO NOTHING）
    - 缺失值转为 None，naive 时间戳按 UTC 规范化，避免写库报错
    返回尝试写入的行数。
    """
    if df is None or df.empty:
        return 0
    cols = [c for c in ("timestamp", "symbol", "price", "volume") if c in df.columns]
    records = df[cols].where(pd.notna(df), None).to_dict(orient="records")
    for rec in records:
        ts = rec.get("timestamp")
        if isinstance(ts, datetime) and ts.tzinfo is None:
            rec["timestamp"] = ts.replace(tzinfo=timezone.utc)
    stmt = _dialect_insert(MarketData).values(records)
    stmt = stmt.on_conflict_do_nothing(index_elements=["timestamp", "symbol"])
    db.execute(stmt)
    db.commit()
    return len(records)
