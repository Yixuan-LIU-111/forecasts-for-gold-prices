"""爬虫适配层：将项目根目录的 7 个独立爬虫模块封装为统一 DataCollector 接口。

适配原则：
- 不重写爬虫逻辑，仅动态加载现有 scrape_*() 函数
- 输出统一标准化字段（对齐 factor_data 表）
- 任何失败（缺依赖/网络/反爬）返回 None 并记录，不抛异常，保证系统可用
"""
from app.core.collectors.base import (
    DataCollector,
    CollectorResult,
    collect_all_factors,
)
from app.core.collectors.adapters import (
    DxyCollector,
    VixCollector,
    TipsCollector,
    GprCollector,
    EpuCollector,
    NewsCollector,
    GoldPriceCollector,
)

__all__ = [
    "DataCollector",
    "CollectorResult",
    "collect_all_factors",
    "DxyCollector",
    "VixCollector",
    "TipsCollector",
    "GprCollector",
    "EpuCollector",
    "NewsCollector",
    "GoldPriceCollector",
]
