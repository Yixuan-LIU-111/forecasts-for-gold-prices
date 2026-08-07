"""鹰鸽事件端点。"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.models.database import get_db
from app.models.schemas import ApiResponse
from app.api.deps import serialize_hawk_dove_events

router = APIRouter(prefix="/api/v1/hawk-dove", tags=["hawk-dove"])


@router.get("/events", response_model=ApiResponse)
def get_hawk_dove_events(
    days: int = Query(7, ge=1, le=90),
    db: Session = Depends(get_db),
):
    return ApiResponse.ok(serialize_hawk_dove_events(db, days))
