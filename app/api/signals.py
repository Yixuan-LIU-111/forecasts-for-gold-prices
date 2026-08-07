"""信号相关端点。"""
import logging

from fastapi import APIRouter, Depends
from sqlalchemy import select, desc
from sqlalchemy.orm import Session

from app.models.database import get_db, Signal
from app.models.schemas import ApiResponse
from app.api.deps import serialize_signal

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/signals", tags=["signals"])


@router.get("/latest", response_model=ApiResponse)
def get_latest_signal(db: Session = Depends(get_db)):
    sig = db.execute(
        select(Signal).order_by(desc(Signal.timestamp)).limit(1)
    ).scalars().first()
    if sig is None:
        logger.warning("get_latest_signal: signals 表无数据！")
    else:
        logger.info("get_latest_signal: 取到信号 direction=%s prob=%s", sig.direction_en, sig.probability)
    return ApiResponse.ok(serialize_signal(sig))


@router.get("/attribution", response_model=ApiResponse)
def get_signal_attribution(db: Session = Depends(get_db)):
    sig = db.execute(
        select(Signal).order_by(desc(Signal.timestamp)).limit(1)
    ).scalars().first()
    if sig is None:
        logger.warning("get_signal_attribution: signals 表无数据！")
        return ApiResponse.ok([])
    return ApiResponse.ok(sig.attribution or [])
