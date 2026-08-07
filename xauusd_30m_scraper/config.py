"""配置：XAU/USD 30 分钟行情获取（新浪财经）。

集中管理 URL、请求头、重试策略、30 分钟窗口参数与落盘路径。
所有“周期”相关参数显式体现固定 30 分钟窗口（项目核心约束）。
"""

from pathlib import Path

# ------------------------------------------------------------------ 周期（固定 30 分钟）
# 项目核心特色：预测 / 行情窗口恒为未来 30 分钟，不可调整。
HORIZON_MINUTES: int = 30
PREDICT_WINDOW: str = "30min"          # 与 V2.0 方案约定的字段命名保持一致
INTERVAL_LABEL: str = "30min"          # 接口 / 数据中的周期标识

# ------------------------------------------------------------------ 数据源（新浪财经实时报价）
# 伦敦现货黄金（XAU/USD）的实时报价代码。
SINA_SYMBOL: str = "hf_XAU"
SERIES_NAME_ZH: str = "伦敦现货黄金 (XAU/USD)"

# 实时报价接口（已验证可用）。历史 / 分时 K 线 JSONP 接口已下线，故采用实时报价聚合。
SINA_QUOTE_URL: str = f"https://hq.sinajs.cn/list={SINA_SYMBOL}"

# 新浪要求带 Referer，否则返回空。
REQUEST_HEADERS: dict = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "*/*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.5",
    "Referer": "https://finance.sina.com.cn",
}

# ------------------------------------------------------------------ 请求与重试
REQUEST_TIMEOUT: float = 10.0          # 单次请求超时（秒）
MAX_RETRIES: int = 5                   # 单次拉取最大重试次数
RETRY_BASE_DELAY: float = 2.0          # 退避基数（秒）
RETRY_MAX_DELAY: float = 30.0          # 退避上限（秒）

# ------------------------------------------------------------------ 定时拉取
# 轮询节奏：每 POLL_INTERVAL_SECONDS 秒拉一次实时报价；
# 30 分钟 K 线由聚合器按 30 分钟边界对齐生成（与轮询节奏解耦）。
POLL_INTERVAL_SECONDS: int = 30

# ------------------------------------------------------------------ 落盘
# 使用项目统一的 data/ 目录，与现有爬虫输出保持一致。
OUTPUT_DIR: Path = Path(__file__).resolve().parent.parent / "data"
LATEST_QUOTE_FILE: Path = OUTPUT_DIR / "xauusd_30m_latest_quote.json"
LATEST_BAR_FILE: Path = OUTPUT_DIR / "xauusd_30m_latest_bar.json"
BARS_HISTORY_FILE: Path = OUTPUT_DIR / "xauusd_30m_bars.jsonl"

# 内存中保留的历史 K 线条数上限（超出仅落盘、不常驻）。
MAX_BARS_IN_MEMORY: int = 240          # 240 * 30min = 5 个交易日

# 时区说明：新浪报价时间为北京时间（UTC+8），本模块按北京时间对齐 30 分钟窗口。
TIMEZONE_LABEL: str = "Asia/Shanghai"
