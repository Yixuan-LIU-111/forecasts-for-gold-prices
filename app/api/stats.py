"""统计端点。"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.models.database import get_db
from app.models.schemas import ApiResponse
from app.api.deps import serialize_accuracy

router = APIRouter(prefix="/api/v1/stats", tags=["stats"])


@router.get("/accuracy", response_model=ApiResponse)
def get_accuracy(
    window: str = Query("7d", description="7d/30d"),
    db: Session = Depends(get_db),
):
    return ApiResponse.ok(serialize_accuracy(db, window))
