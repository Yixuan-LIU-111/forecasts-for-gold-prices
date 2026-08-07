"""集中配置：路径、特征定义、模型超参、划分比例。

所有魔法数字集中在此，保证实验可复现、可审计。
超参数取值严格对齐《项目方案V1.0.md》第 9.4 / 9.5 章。
"""

from pathlib import Path

# ---------------------------------------------------------------- 路径
ROOT = Path(__file__).resolve().parent.parent
MODEL_DIR = Path(__file__).resolve().parent

SAMPLE_XLSX = ROOT / "docs" / "data_sample" / "20260803之前的历史数据.xlsx"
SAMPLE_SHEET = "数据"

DATA_DIR = MODEL_DIR / "data"
ARTIFACT_DIR = MODEL_DIR / "artifacts"
REPORT_DIR = MODEL_DIR / "reports"

GOLD_RAW_CSV = DATA_DIR / "gold_gc_daily_raw.csv"      # 抓取缓存（原始）
DATASET_CSV = DATA_DIR / "dataset_merged.csv"           # 对齐合并后的建模底表
FEATURES_CSV = DATA_DIR / "features.csv"                # 特征工程产物

for _d in (DATA_DIR, ARTIFACT_DIR, REPORT_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------- 数据源
# 新浪财经全球期货日K线（COMEX 黄金 GC 连续合约）
SINA_GC_URL = (
    "https://stock.finance.sina.com.cn/futures/api/jsonp.php/"
    "var%20_gc=/GlobalFuturesService.getGlobalFuturesDailyKLine?symbol=GC"
)
REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Referer": "https://finance.sina.com.cn/",
}
REQUEST_TIMEOUT = 30

# ---------------------------------------------------------------- 新闻 / 情感特征
# 新闻原始数据来自 news_scraper_llm 的输出缓存（含 title/summary/published_at，
# 以及 LLM 已分析的 sentiment_score）；本模块在此基础上补充鹰鸽分数并做 bar 对齐。
NEWS_DIR = ROOT / "data" / "news_scraper_output"
SENTIMENT_CACHE_CSV = DATA_DIR / "sentiment_features.csv"   # 情感特征底表缓存

# LLM 情感 / 鹰鸽提取配置（方案文档 §9.2/§9.3 要求 LLM）。
# provider: "openai" | "ollama" | "rule"
#   - openai ：调用 OpenAI 兼容接口（含 qwen-turbo 等），需 OPENAI_API_KEY
#   - ollama ：本地 Ollama（默认 http://localhost:11434），无需密钥
#   - rule   ：关键词规则引擎（离线、可复现、零依赖）—— 默认降级路径
# 无论哪种 provider，最终都降级到 rule，保证流水线在离线环境端到端跑通。
LLM_PROVIDER = "rule"
OPENAI_API_KEY = ""          # 运行时可经环境变量 OPENAI_API_KEY 注入
OPENAI_BASE_URL = "https://api.openai.com/v1"
OPENAI_MODEL = "gpt-4o-mini"
OLLAMA_BASE_URL = "http://localhost:11434"
LLM_TIMEOUT = 30
LLM_MAX_CONCURRENCY = 4

# Excel 中的指标列 -> 标准列名（依据表头「指标简称」行）
INDICATOR_MAP = {
    "标准普尔500波动率指数(VIX)": "vix",
    "全球:地缘政治风险指数(参考十家报纸)": "gpr",
    "美国:经济政策不确定性指数": "epu",
    "美元指数": "dxy",
    "美国:国债实际收益率:10年": "tips",
}

# ---------------------------------------------------------------- 预测目标（时间语义）
# 方案文档核心目标：预测「未来 30 分钟」黄金价格方向（涨/跌）。
# 文档以 30 分钟级 bar 为基准：shift(-30) = 看向 30 根 bar = 30 分钟。
TARGET_HORIZON_MINUTES = 30          # 预测目标时长：未来 30 分钟
DESIGN_BAR_INTERVAL_MINUTES = 30     # 设计频率：1 根 bar = 30 分钟（文档原始假设）
# 当前样本数据为日频（1440 分钟 / 根），按用户已批准决策作「日频近似」代理。
# 接入真实 30 分钟 bar 行情时，将 ACTUAL_BAR_INTERVAL_MINUTES 改为 30，
# 则 HORIZON_BARS 自动等于 TARGET_HORIZON_MINUTES / 30 = 1 根 = 30 分钟。
ACTUAL_BAR_INTERVAL_MINUTES = 1440

# 前瞻 bar 数（文档 shift(-30)）。日频近似下保留 30 根 = 30 个交易日作为代理跨度；
# 该值即模型真正使用的标签偏移量，与文档 shift(-30) 严格一致。
HORIZON = 30
ROLL_WINDOW = 30      # 滚动窗口（bar 数），与文档 rolling(30) 一致（设计上覆盖 30 分钟窗口）

# 给定实际 bar 间隔，计算「未来 30 分钟」对应的前瞻 bar 数（供真实 30 分钟数据使用）
def horizon_bars_for(interval_minutes: int = ACTUAL_BAR_INTERVAL_MINUTES) -> int:
    """未来 TARGET_HORIZON_MINUTES 分钟在当前数据频率下 = 多少根 bar（向上取整）。"""
    import math
    return max(1, math.ceil(TARGET_HORIZON_MINUTES / interval_minutes))

PREDICTION_TARGET = "未来30分钟黄金价格方向（涨=1 / 跌=0）"

# 补充对照跨度（仅用于稳健性参考，不改变主模型定义）
AUX_HORIZONS = [1, 5]

# ---------------------------------------------------------------- 特征分组
# --- v1：文档字面实现（保留用于对照，已诊断出严重非平稳）---
# P0：方案文档第 3.3 章明确列出的特征（价格序列 + 市场特征）
FEATURES_PRICE = ["return_30", "volatility_30", "spread"]
FEATURES_MARKET = ["dxy_return", "tips_change", "vix_level"]
# P1：样本数据额外提供、文档标记为「延后」的风险类指标
FEATURES_RISK = ["gpr_level", "gpr_change", "epu_level", "epu_change"]

# --- v2：平稳化改造版 ---
# 诊断发现 spread(5.19σ) / epu_level(2.25σ) / gpr_level(1.33σ) / volatility_30(1.24σ)
# 在 train→test 间发生严重分布漂移（金价从 1130 涨到 5446，绝对量纲失效）。
# 改造原则：绝对量纲 → 相对量纲；水平值 → 滚动 z-score（仅用历史窗口，无前视）。
FEATURES_PRICE_STAT = ["return_30", "volatility_ratio", "spread_pct"]
FEATURES_MARKET_STAT = ["dxy_return", "tips_change", "vix_z"]
FEATURES_RISK_STAT = ["gpr_z", "gpr_change_pct", "epu_z", "epu_change_pct"]

FEATURES_SENTIMENT = ["sentiment_score", "sentiment_mean_30", "sentiment_max_30",
                       "hawkish_score", "hawkish_change"]

FEATURE_SETS = {
    # 消融对比 A 组：严格文档 P0 范围（原始量纲）
    "p0_doc": FEATURES_PRICE + FEATURES_MARKET,
    # 消融对比 B 组：纳入 GPR / EPU（原始量纲）
    "full": FEATURES_PRICE + FEATURES_MARKET + FEATURES_RISK,
    # 平稳化版本（宏观指标，不含情感）
    "p0_stat": FEATURES_PRICE_STAT + FEATURES_MARKET_STAT,
    "full_stat": FEATURES_PRICE_STAT + FEATURES_MARKET_STAT + FEATURES_RISK_STAT,
    # 平稳化 + LLM 情感 / 鹰鸽特征（方案文档 §3.3/§9.4 要求纳入的输入变量）
    "full_stat_sent": (FEATURES_PRICE_STAT + FEATURES_MARKET_STAT
                       + FEATURES_RISK_STAT + FEATURES_SENTIMENT),
}
PRIMARY_FEATURE_SET = "full_stat_sent"   # 默认含情感特征；无情感数据时自动回退到 full_stat

# 滚动标准化窗口（约 1 年交易日），仅回看，杜绝前视偏差
ZSCORE_WINDOW = 252

# 情感 / 鹰鸽特征（方案文档 §3.3/§9.2/§9.3/§9.4）：
# sentiment_score ∈ [-1,+1]（LLM 黄金利多/利空），
# hawkish_score   ∈ [-1,+1]（鹰派=+1 / 鸽派=-1，文档：鹰派→利空黄金）。
# 管道通过 sentiment_features 模块接入；无情感数据时训练自动跳过（见 features.attach_sentiment_features）。

# ---------------------------------------------------------------- 数据划分
# 方案文档 §9.5：训练 70% / 验证 15% / 测试 15%，按时间顺序划分
TRAIN_RATIO = 0.70
VALID_RATIO = 0.15
TEST_RATIO = 0.15

# Purge / Embargo：目标变量使用 t+HORIZON 的价格，导致划分边界处
# 前一段末尾样本的前瞻窗口与后一段重叠 → 信息泄露。
# 在每个边界剔除 HORIZON 根 bar（López de Prado purging），彻底切断重叠。
PURGE_BARS = HORIZON

# Walk-Forward 验证折数
WALK_FORWARD_SPLITS = 5

# ---------------------------------------------------------------- 模型超参
# 方案文档 §9.4 LightGBM
LGB_PARAMS = {
    "objective": "binary",
    "metric": "binary_logloss",
    "num_leaves": 31,
    "learning_rate": 0.05,
    "n_estimators": 200,
    "verbose": -1,
    "random_state": 42,
    "n_jobs": -1,
}
LGB_EARLY_STOPPING_ROUNDS = 20

# 早停监控指标：文档写的是 binary_logloss，但验证段与训练段正类先验
# 差异达 28 个百分点（52% vs 79%），logloss 被先验偏移主导，
# 实测导致 best_iteration=1（模型未训练）。改用 AUC（排序型指标，
# 对先验偏移不敏感）。这是对文档的必要工程修正，已在报告中说明。
EARLY_STOP_METRIC_LGB = "auc"
EARLY_STOP_METRIC_XGB = "auc"

# 方案文档 §9.4 XGBoost
XGB_PARAMS = {
    "objective": "binary:logistic",
    "max_depth": 6,
    "learning_rate": 0.05,
    "n_estimators": 200,
    "eval_metric": "logloss",
    "random_state": 42,
    "n_jobs": -1,
}
XGB_EARLY_STOPPING_ROUNDS = 20

# 方案文档 §9.4 双模型集成：p_final = 0.6 * p_lgb + 0.4 * p_xgb
ENSEMBLE_W_LGB = 0.6
ENSEMBLE_W_XGB = 0.4

# 方案文档 §9.5 过拟合检测阈值
OVERFIT_GAP_THRESHOLD = 0.15

RANDOM_SEED = 42
