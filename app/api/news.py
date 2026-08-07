"""新闻端点。"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.models.database import get_db
from app.models.schemas import ApiResponse
from app.api.deps import serialize_news

router = APIRouter(prefix="/api/v1/news", tags=["news"])


@router.get("", response_model=ApiResponse)
def get_news(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    return ApiResponse.ok(serialize_news(db, limit, offset))
