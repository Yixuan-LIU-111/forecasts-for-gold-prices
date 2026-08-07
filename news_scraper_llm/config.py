"""
配置管理
"""
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# 始终从本文件所在目录读取 .env，无论在哪里执行 `python -m news_scraper_llm`
_BASE_DIR = Path(__file__).resolve().parent
# 项目根目录（news_scraper_llm 的父目录），data/ 在此处
_PROJECT_ROOT = _BASE_DIR.parent


class Settings(BaseSettings):
    """抓取与 LLM 分析配置"""

    model_config = SettingsConfigDict(
        env_file=str(_BASE_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- LLM ---
    # 默认使用阿里云百炼(DashScope)免费模型 qwen-turbo（OpenAI 兼容端点）。
    # 如需切回官方 OpenAI，设置 OPENAI_BASE_URL=https://api.openai.com/v1 且 OPENAI_MODEL=gpt-4o-mini。
    # 不填则留空；main.py 会在运行时给出友好提示（避免导入即崩溃）
    openai_api_key: str = ""
    openai_model: str = "qwen-turbo"
    openai_base_url: str | None = "https://ws-1h7z52vtt1oj8b3p.cn-beijing.maas.aliyuncs.com/compatible-mode/v1"
    openai_temperature: float = 0.0
    openai_timeout: int = 30
    llm_max_concurrency: int = 3

    # LLM 失败重试：单次分析在最终降级为中性前的重试次数与退避基数（秒，指数退避）
    llm_max_retries: int = 2
    llm_retry_backoff_s: float = 1.0

    # --- 抓取 ---
    headless: bool = True
    browser: str = "chromium"
    page_timeout_ms: int = 60_000
    wait_for_selector_timeout_ms: int = 10_000
    max_items_per_site: int = 10
    polite_delay_ms: int = 1_000          # 站点内请求间隔
    fetch_article_summaries: bool = False  # 是否进入详情页抓取正文摘要
    user_agent: str = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )

    # --- 情感分析模式 ---
    # general = 通用新闻正/负/中；gold = 针对黄金价格（利多/利空）
    sentiment_mode: str = "general"

    # --- 持久化（数据库）---
    # 复用项目统一分析库 data/gold_predictor.db（与 app 共用，SQLAlchemy 2.0）。
    # 默认指向项目根目录下的 data/gold_predictor.db；可用环境变量 DATABASE_URL 覆盖
    # （如换成 PostgreSQL：postgresql+psycopg://user:pass@host:5432/dbname）。
    database_url: str = f"sqlite:///{_PROJECT_ROOT / 'data' / 'gold_predictor.db'}"
    db_echo: bool = False

    # --- 输出 ---
    output_dir: str = "./data/news_scraper_output"
    output_json: bool = True
    output_csv: bool = True


settings = Settings()
