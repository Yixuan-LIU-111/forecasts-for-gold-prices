"""
全局配置（合并当前项目与 forecasts-for-gold-prices-main 后端）。

- 采用 pydantic-settings 读取 .env / 环境变量，集中管理数据库连接等参数。
- 既保留当前项目的大写字段（DATABASE_URL / DB_* / APP_ENV / LOG_LEVEL，供
  app/models/database.py、app/core/data_collector.py 等旧代码使用），
  又提供 forecasts-for-gold-prices-main 后端所需的 lowercase 字段与派生属性
  （database_url / is_sqlite / demo_mode / api_host / api_port / openai_* 等）。
- 大写字段以小写 canonical 字段的 @property 别名形式暴露，旧代码无需改动。
- 路径管理已迁移至 app.frozen 模块，同时兼容开发与 PyInstaller 打包环境。
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

from app.frozen import (
    PROJECT_ROOT,
    EXE_DIR,
    DATA_DIR,
    MODELS_DIR,
    DEMO_DATA_DIR,
    DOT_ENV_PATH,
    IS_FROZEN,
    ensure_runtime_dirs,
)

# 向后兼容：其他模块仍从 app.config 导入 PROJECT_ROOT
__all__ = ["PROJECT_ROOT", "EXE_DIR", "DATA_DIR", "MODELS_DIR", "DEMO_DATA_DIR",
           "DOT_ENV_PATH", "IS_FROZEN", "ensure_runtime_dirs", "Settings", "get_settings", "settings"]


class Settings(BaseSettings):
    """应用全局配置。

    所有字段均可通过环境变量覆盖；默认值对齐方案与 docker-compose 约定。
    """

    model_config = SettingsConfigDict(
        env_file=str(DOT_ENV_PATH),
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
    # OpenAI 兼容网关地址（如阿里云百炼 qwen 系列）；为空则用官方默认端点
    openai_base_url: str = ""
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


def _load_scraper_llm_env() -> dict[str, str]:
    """读取 news_scraper_llm/.env 中的 OPENAI_* 配置（不复制密钥，只共享同一份来源）。

    背景：LLM 凭据此前只配置在爬虫子项目里，导致 app 侧 has_openai=False，
    中文标题/情感分析只能走规则降级。此处作为兜底来源读取，保持单一密钥来源。
    仅在 app 自身未配置时生效，app 级 .env 或环境变量始终优先。
    """
    env_path = PROJECT_ROOT / "news_scraper_llm" / ".env"
    if not env_path.exists():
        return {}
    out: dict[str, str] = {}
    try:
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip().upper()
            if key in {"OPENAI_API_KEY", "OPENAI_MODEL", "OPENAI_BASE_URL"}:
                out[key] = val.strip().strip('"').strip("'")
    except Exception:  # noqa: BLE001 - 配置读取失败不应阻断启动
        return {}
    return out


@lru_cache
def get_settings() -> Settings:
    """返回进程级配置单例（main 风格：启动时确保目录存在）。"""
    ensure_runtime_dirs()
    s = Settings()

    # app 未配置 LLM 时，回退复用爬虫子项目的 OpenAI 兼容配置
    if not s.openai_api_key:
        scraper_env = _load_scraper_llm_env()
        if scraper_env.get("OPENAI_API_KEY"):
            s.openai_api_key = scraper_env["OPENAI_API_KEY"]
            if scraper_env.get("OPENAI_MODEL"):
                s.openai_model = scraper_env["OPENAI_MODEL"]
            if scraper_env.get("OPENAI_BASE_URL"):
                s.openai_base_url = scraper_env["OPENAI_BASE_URL"]
    return s


# 全局可导入的配置实例（app 各模块统一从此处取用）
settings = get_settings()
