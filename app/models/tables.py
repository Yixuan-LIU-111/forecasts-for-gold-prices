"""
向后兼容重导出层。

当前项目的 core 模块（data_collector / sentiment / signal_generator / hawk_dove）
通过 `from app.models.tables import ...` 访问 ORM。合并后 ORM 统一收敛到
`app.models.database`，此处仅做重导出，并保留历史别名 Signals / BacktestResults，
避免改动现有业务代码。
"""
from app.models.database import (
    Base,
    EconomicCalendar,
    FactorData,
    HawkDoveEvent,
    MarketData,
    News,
    Sentiment,
    Signal,
    BacktestResult,
    engine,
    get_db,
    init_db,
    SessionLocal,
)

# 历史别名
Signals = Signal
BacktestResults = BacktestResult

__all__ = [
    "Base",
    "engine",
    "SessionLocal",
    "get_db",
    "init_db",
    "MarketData",
    "News",
    "Sentiment",
    "Signal",
    "Signals",
    "HawkDoveEvent",
    "BacktestResult",
    "BacktestResults",
    "FactorData",
    "EconomicCalendar",
]
