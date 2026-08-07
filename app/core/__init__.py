"""核心层（数据采集 / 因子 / 情感 / 鹰鸽 / 信号 / 回测 / 质量）。

落库相关模块：
- data_collector:   DataCollector 抽象基类 + store_market_data 共享写库
- factor_collectors: 存量 6 scraper 接入统一接口并写库（B-7）
- news_collector:   新闻采集封装 + 去重（B-5/B-6）
- sentiment:         情感结果落库 + 缓存命中（C-1/C-2）
- hawk_dove:         鹰鸽指数打分 + 落库（C-6）
- signal_generator:  信号生成 + 落库（E-3）
- backtest:          回测模拟 + 落库（E-11）
- data_quality:      断档/跳变质量校验（B-9）
- bootstrap_data:    历史数据预加载脚本（B-8）
"""
from app.core.data_collector import DataCollector, YFinanceCollector, store_market_data
from app.core.factor_collectors import (
    DXYCollector,
    VIXCollector,
    TIPSCollector,
    GPRCollector,
    EPUCollector,
    CalendarCollector,
    collect_all_factors,
)
from app.core.news_collector import NewsAPICollector
from app.core.sentiment import SentimentStorer
from app.core.hawk_dove import score_text, process_news_to_events, latest_events
from app.core.signal_generator import generate_signal, latest_signal
from app.core.backtest import run_backtest, get_latest_backtest, BacktestParams
from app.core.data_quality import run_quality_checks, find_gaps, find_price_jumps
from app.core.bootstrap_data import bootstrap as run_bootstrap
# —— 以下为 forecasts-for-gold-prices-main 后端新增模块（合并接入）——
from app.core.predictor import WeightedPredictor, train_synthetic_model
from app.core.scheduler import start_scheduler, stop_scheduler
from app.core.feature_engineer import get_feature_columns
from app.core.collectors.adapters import (
    DxyCollector,
    VixCollector,
    TipsCollector,
    GprCollector,
    EpuCollector,
    NewsCollector,
)
from app.core.collectors.base import collect_gold_price
from app.core.seed import init_app as seed_init_app

__all__ = [
    "DataCollector",
    "YFinanceCollector",
    "store_market_data",
    "DXYCollector",
    "VIXCollector",
    "TIPSCollector",
    "GPRCollector",
    "EPUCollector",
    "CalendarCollector",
    "collect_all_factors",
    "NewsAPICollector",
    "SentimentStorer",
    "score_text",
    "process_news_to_events",
    "latest_events",
    "generate_signal",
    "latest_signal",
    "run_backtest",
    "get_latest_backtest",
    "BacktestParams",
    "run_quality_checks",
    "find_gaps",
    "find_price_jumps",
    "run_bootstrap",
    "WeightedPredictor",
    "train_synthetic_model",
    "start_scheduler",
    "stop_scheduler",
    "get_feature_columns",
    "DxyCollector",
    "VixCollector",
    "TipsCollector",
    "GprCollector",
    "EpuCollector",
    "NewsCollector",
    "collect_gold_price",
    "seed_init_app",
]
