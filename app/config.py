"""
全局配置（合并当前项目与 forecasts-for-gold-prices-main 后端）。

- 采用 pydantic-settings 读取 .env / 环境变量，集中管理数据库连接等参数。
- 既保留当前项目的大写字段（DATABASE_URL / DB_* / APP_ENV / LOG_LEVEL，供
  app/models/database.py、app/core/data_collector.py 等旧代码使用），
  又提供 forecasts-for-gold-prices-main 后端所需的 lowercase 字段与派生属性
  （database_url / is_sqlite / demo_mode / api_host / api_port / openai_* 等）。
- 大写字段以小写 canonical 字段的 @property 别名形式暴露，旧代码无需改动。
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# 项目根目录：app/config.py 的上两级
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEMO_DATA_DIR = PROJECT_ROOT / "app" / "dashboard" / "demo_data"
DATA_DIR = PROJECT_ROOT / "data"
MODELS_DIR = PROJECT_ROOT / "models"


class Settings(BaseSettings):
    """应用全局配置。

    所有字段均可通过环境变量覆盖；默认值对齐方案与 docker-compose 约定。
    """

    model_config = SettingsConfigDict(
        env_file=str(PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # —— 数据库（SQLite 文件型，无服务器；可切回 PostgreSQL）——
    database_url: str = f"sqlite:///{DATA_DIR / 'gold_predictor.db'}"
    db_pool_size: int = 5
    db_max_overflow: int = 10
    db_pool_timeout: int = 30
    db_pool_recycle: int = 1800
    db_echo: bool = False

    # —— 运行模式（main 后端）——
    demo_mode: bool = True
    debug: bool = True

    # —— LLM（main 后端）——
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    llm_daily_budget_usd: float = 5.0

    # —— 新闻（main 后端）——
    newsapi_key: str = ""
    newsapi_daily_limit: int = 100

    # —— 调度（main 后端）——
    signal_interval_seconds: int = 300
    collect_interval_seconds: int = 60

    # —— 实时爬取与刷新（本次优化新增）——
    # 调度器总开关：默认开启；设为 false 则完全不启动后台任务（纯静态数据）。
    # 注意：即便 demo_mode=True，只要本开关为 true，新闻实时爬取任务也会运行
    # （它依赖 Playwright + LLM，不依赖任何付费外部 API）。
    scheduler_enabled: bool = True
    # 新闻实时爬取任务开关（定时运行 news_scraper_llm 抓取 4 站点 + LLM 情感分析）
    news_scrape_enabled: bool = True
    # 新闻爬取周期（秒）。前端轮询周期（60s）远小于此值，故新数据在爬取完成后 60s 内即呈现。
    news_scrape_interval_seconds: int = 300
    # 定时任务每次每站点抓取条数（控制 LLM 调用量与耗时，手动运行时仍用各自 .env 的 max_items_per_site）
    news_scrape_max_items: int = 4

    # —— 应用 ——
    app_env: str = "development"
    log_level: str = "INFO"
    api_host: str = "0.0.0.0"
    api_port: int = 8000

    # —— 派生属性（main 后端风格）——
    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    @property
    def has_openai(self) -> bool:
        return bool(self.openai_api_key)

    @property
    def has_newsapi(self) -> bool:
        return bool(self.newsapi_key)

    # —— 大写别名（兼容当前项目旧代码 app.config.DATABASE_URL 等）——
    @property
    def DATABASE_URL(self) -> str:
        return self.database_url

    @property
    def DB_ECHO(self) -> bool:
        return self.db_echo

    @property
    def DB_POOL_SIZE(self) -> int:
        return self.db_pool_size

    @property
    def DB_MAX_OVERFLOW(self) -> int:
        return self.db_max_overflow

    @property
    def DB_POOL_TIMEOUT(self) -> int:
        return self.db_pool_timeout

    @property
    def DB_POOL_RECYCLE(self) -> int:
        return self.db_pool_recycle

    @property
    def APP_ENV(self) -> str:
        return self.app_env

    @property
    def LOG_LEVEL(self) -> str:
        return self.log_level


@lru_cache
def get_settings() -> Settings:
    """返回进程级配置单例（main 风格：启动时确保目录存在）。"""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    return Settings()


# 全局可导入的配置实例（app 各模块统一从此处取用）
settings = get_settings()
