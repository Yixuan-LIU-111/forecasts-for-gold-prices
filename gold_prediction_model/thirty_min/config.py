"""统一配置入口 —— 黄金 30 分钟预测模型（LLM 情感 + 量化集成）。

项目硬约束（见《项目方案V2.0.md》§0.1）：
- 预测窗口固定为未来 30 分钟，不可调为日频等其他范围。
- 本模块所有「周期 / 窗口」参数均显式体现 30 分钟。

本文件是 thirty_min 包的唯一配置入口，所有子模块通过相对导入
`from . import config` 获取配置，避免旧日频模块 `import config` 的顶层冲突。
"""

from __future__ import annotations

from pathlib import Path

# ------------------------------------------------------------------ 周期（固定 30 分钟，项目核心约束）
HORIZON_MINUTES: int = 30                      # 预测窗口长度（分钟）
PREDICT_WINDOW: str = "30min"                  # 字段 / 接口周期标识
BAR_MINUTES: int = 30                          # 一根 K 线 = 30 分钟
HORIZON_BARS: int = 1                          # 目标变量前瞻 bar 数 = 30min / 30min = 1

# ------------------------------------------------------------------ 路径（统一入口）
REPO_ROOT = Path(__file__).resolve().parent.parent.parent     # .../forecasts for gold prices
DATA_DIR = REPO_ROOT / "data"
NEWS_DIR = DATA_DIR / "news_scraper_output"

PKG_DIR = Path(__file__).resolve().parent
ARTIFACT_DIR = PKG_DIR / "artifacts"
REPORT_DIR = PKG_DIR / "reports"
LOGS_DIR = PKG_DIR / "logs"
for _d in (ARTIFACT_DIR, REPORT_DIR, LOGS_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# xauusd_30m_scraper 的落盘契约（解耦读取，不 import 该包）
PRICE_BARS_HISTORY = DATA_DIR / "xauusd_30m_bars.jsonl"
PRICE_BAR_LATEST = DATA_DIR / "xauusd_30m_latest_bar.json"

# 真实日频 COMEX 黄金（由 gold_prediction_model/data_loader 抓取缓存于 gold_prediction_model/data/）
GOLD_DAILY_CSV = PKG_DIR.parent / "data" / "gold_gc_daily_raw.csv"
# 宏观样本 Excel（含真实 10 年日频 GPR/EPU 新闻压力指数）
MACRO_SAMPLE_XLSX = REPO_ROOT / "docs" / "data_sample" / "20260803之前的历史数据.xlsx"
# 新闻情感落库（news_scraper_llm → SQLite）
NEWS_DB_PATH = DATA_DIR / "gold_predictor.db"
# 真实锚定 30m 构造参数（价格轨迹 100% 真实，日内为 realism 模拟）
REAL_ANCHORED_PER_DAY = 48
REAL_ANCHORED_SEED = 42

# 时区：新浪 / 新闻均为北京时间口径
TIMEZONE_LABEL = "Asia/Shanghai"

# ------------------------------------------------------------------ 数据层参数
MIN_BARS_FOR_TRAIN = 200        # 真实 30 分钟 bar 少于此数时，示例入口回退合成数据
NEWS_LOOKBACK_BARS = 20         # 新闻事件归入「≤事件时刻」的最新 bar（前视安全）
FACTOR_EFFECTIVE_HOUR = 23.5    # 日频因子视为当日 23:30 后生效（前视安全 ffill）

# ------------------------------------------------------------------ 特征窗口
SENTIMENT_WINDOW_BARS = 20      # 情感聚合回望窗口（≈10 小时）
MA_WINDOW_BARS = 20             # 价格 MA 窗口
VOL_WINDOW_BARS = 20            # 波动率回望窗口

# ------------------------------------------------------------------ 特征分组
FEATURES_TECHNICAL = [
    "ret_1", "ret_vol", "ma_dev", "range_pct", "log_ret",
    # 增强：30m 微观结构信号
    "rsi", "vol_z", "ret_z", "ma_dev_long", "sampling_count",
]
FEATURES_SENTIMENT = [
    "sent_mean", "sent_absmax", "sent_std",
    "news_density", "sent_conf_mean", "has_news",
    # 真实 GPR/EPU 新闻压力量化情感
    "gpr_news_sent", "epu_news_sent", "macro_news_sent", "macro_news_sent_roll",
]
FEATURES_MARKET = [
    "dxy_return", "vix_level", "vix_change",
    "tips_change",
]
# 不含情感的对照特征集（用于消融）
FEATURES_NO_SENTIMENT = FEATURES_TECHNICAL + FEATURES_MARKET
FEATURES_ALL = FEATURES_TECHNICAL + FEATURES_SENTIMENT + FEATURES_MARKET
PRIMARY_FEATURE_SET = "all"

# ------------------------------------------------------------------ 数据划分（时序 70/15/15）
TRAIN_RATIO = 0.70
VALID_RATIO = 0.15
TEST_RATIO = 0.15
PURGE_BARS = HORIZON_BARS        # 切断标签窗口重叠（López de Prado purging）

# ------------------------------------------------------------------ 模型超参（对齐方案 §9.4）
ENSEMBLE_W_LGB = 0.6
ENSEMBLE_W_XGB = 0.4

LGB_PARAMS = {
    "objective": "binary",
    "metric": "binary_logloss",
    "num_leaves": 31,
    "learning_rate": 0.05,
    "n_estimators": 300,
    "verbose": -1,
    "random_state": 42,
    "n_jobs": -1,
}
LGB_EARLY_STOPPING_ROUNDS = 30

XGB_PARAMS = {
    "objective": "binary:logistic",
    "max_depth": 6,
    "learning_rate": 0.05,
    "n_estimators": 300,
    "eval_metric": "logloss",
    "random_state": 42,
    "n_jobs": -1,
}
XGB_EARLY_STOPPING_ROUNDS = 30

# 早停指标改用 AUC（对正负先验偏移不敏感）
EARLY_STOP_METRIC_LGB = "auc"
EARLY_STOP_METRIC_XGB = "auc"

# ------------------------------------------------------------------ 推理 / 信号阈值
SIGNAL_LONG_THRESHOLD = 0.60     # p >= 0.60 → 看涨
SIGNAL_SHORT_THRESHOLD = 0.40    # p <= 0.40 → 看跌
CONFIDENCE_FLOOR = 0.55          # 置信度（|p-0.5|*2）< 此值 → 观望

RANDOM_SEED = 42
