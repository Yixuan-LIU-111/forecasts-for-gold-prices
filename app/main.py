"""FastAPI 应用入口。

启动流程：
1. 初始化数据库表 + 引导种子数据（首次启动从 demo_data 导入）
2. 挂载 12 个 RESTful 端点（对齐前端 client.py）
3. 可选：启动后台调度器（实时模式下周期采集 + 生成信号）

启动：
    uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
"""
from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pathlib import Path

from app.config import settings
from app.core.seed import init_app
from app.api import (
    signals, market, factors, news, backtest, stats, hawk_dove, system,
)

logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="黄金价格预测系统 API",
    version="1.0.0",
    description="12 个 RESTful 端点，对齐前端 client.py 契约",
)

# CORS：允许前端 Streamlit 跨域访问
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 挂载路由
app.include_router(signals.router)
app.include_router(market.router)
app.include_router(factors.router)
app.include_router(news.router)
app.include_router(backtest.router)
app.include_router(stats.router)
app.include_router(hawk_dove.router)
app.include_router(system.router)


@app.on_event("startup")
def on_startup() -> None:
    """启动时初始化数据库 + 种子数据，并按配置启动后台调度器。"""
    logger.info("启动应用，DEMO_MODE=%s，SCHEDULER_ENABLED=%s", settings.demo_mode, settings.scheduler_enabled)
    init_app()
    # 启动后台调度器：由 SCHEDULER_ENABLED 控制总开关。
    # 调度器内部会在 demo 模式下也挂载「新闻实时爬取」任务（不依赖付费外部 API），
    # 从而让 demo 系统也能展示真实、自动刷新的新闻情感数据。
    if settings.scheduler_enabled:
        try:
            from app.core.scheduler import start_scheduler
            start_scheduler()
        except Exception as e:  # noqa: BLE001
            logger.warning("调度器启动失败（不影响 API）: %s", e)
    # 冷启动训练基线模型（无模型文件时）
    try:
        from app.core.predictor import WeightedPredictor, train_synthetic_model
        m = WeightedPredictor.load()
        if not m.trained:
            logger.info("冷启动：训练合成基线模型")
            train_synthetic_model()
    except Exception as e:  # noqa: BLE001
        logger.warning("基线模型训练失败（不影响 API）: %s", e)


@app.on_event("shutdown")
def on_shutdown() -> None:
    try:
        from app.core.scheduler import stop_scheduler
        stop_scheduler()
    except Exception:  # noqa: BLE001
        pass


# 同源托管前端页面：让预览/浏览器与 API 处于同一 origin，避免跨 localhost 取数失败
_FRONTEND_HTML = Path(__file__).resolve().parent.parent / "frontend" / "dashboard.html"


@app.get("/", tags=["ui"])
@app.get("/dashboard", tags=["ui"])
@app.get("/dashboard.html", tags=["ui"])
def serve_dashboard():
    return FileResponse(_FRONTEND_HTML)


@app.get("/health", tags=["root"])
def health():
    return {"status": "ok"}
