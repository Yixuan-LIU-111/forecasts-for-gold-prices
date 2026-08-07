"""系统状态端点。"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from app.config import settings
from app.models.database import get_db, MarketData, FactorData, News, Signal, DataSource
from app.models.schemas import (
    ApiResponse, SystemStatusOut, ApiUsage, ModelInfoOut, DataSourceOut,
)
from app.api.deps import serialize_data_sources

router = APIRouter(prefix="/api/v1/system", tags=["system"])


def _db_type() -> str:
    url = settings.database_url.lower()
    if url.startswith("sqlite"):
        return "SQLite"
    if "postgresql" in url:
        return "PostgreSQL"
    return "Unknown"


def _model_info() -> ModelInfoOut:
    try:
        from app.core.predictor import WeightedPredictor
        model = WeightedPredictor.load()
        is_trained = bool(getattr(model, "trained", False))
        name = getattr(model, "name", None) or ("LightGBM+XGBoost 加权" if is_trained else "未训练")
    except Exception:
        is_trained = False
        name = "不可用"
    real = is_trained and not settings.demo_mode
    status = "loaded" if real else ("synthetic_baseline" if settings.demo_mode else "unavailable")
    return ModelInfoOut(
        name=name,
        status=status,
        is_real_model=real,
        demo_mode=settings.demo_mode,
        signal_threshold=0.55,
        available_indicators=[
            "DXY", "TIPS(10Y实际利率)", "VIX", "GPR(地缘风险)",
            "情感均值", "鹰鸽指数",
        ],
    )


@router.get("/status", response_model=ApiResponse)
def get_system_status(db: Session = Depends(get_db)):
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "")

    # 数据采集状态
    last_factor = db.execute(
        select(FactorData.timestamp).order_by(FactorData.timestamp.desc()).limit(1)
    ).scalar()
    db_ok = last_factor is not None
    data_collection = f"正常（最后更新 {last_factor}）" if db_ok else "无数据"

    # LLM 服务
    llm_service = "已配置 OpenAI" if settings.has_openai else "未配置（规则引擎降级）"

    # 数据库连接
    db_connection = "正常"

    # 模型加载
    model = _model_info()
    model_loaded = model.name if model.status == "loaded" else (
        "合成基线模型（演示）" if model.status == "synthetic_baseline" else "未加载"
    )

    status = SystemStatusOut(
        status="ok" if db_ok else "warning",
        data_collection=data_collection,
        llm_service=llm_service,
        db_connection=db_connection,
        db_type=_db_type(),
        model_loaded=model_loaded,
        model_info=model,
        api_usage=ApiUsage(today=0.0, limit=settings.llm_daily_budget_usd, name="OpenAI"),
        timestamp=now,
        mode="演示模式" if settings.demo_mode else "实时模式",
    )
    return ApiResponse.ok(status.model_dump())


@router.get("/data-sources", response_model=ApiResponse)
def get_data_sources(db: Session = Depends(get_db)):
    """返回各指标对应的真实采集源（数据源配置面板使用）。"""
    rows = serialize_data_sources(db)
    return ApiResponse.ok([DataSourceOut(**r).model_dump() for r in rows])
