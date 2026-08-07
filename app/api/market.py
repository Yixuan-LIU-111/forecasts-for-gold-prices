"""行情端点。"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.models.database import get_db
from app.models.schemas import ApiResponse
from app.api.deps import serialize_market

router = APIRouter(prefix="/api/v1/market", tags=["market"])


@router.get("/price", response_model=ApiResponse)
def get_market_price(
    range_hours: str = Query("4h", description="1h/4h/1d/3d/7d"),
    db: Session = Depends(get_db),
):
    return ApiResponse.ok(serialize_market(db, range_hours))
