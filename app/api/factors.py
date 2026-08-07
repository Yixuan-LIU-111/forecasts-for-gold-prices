"""6 因子端点。"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.models.database import get_db
from app.models.schemas import ApiResponse
from app.api.deps import serialize_factors

router = APIRouter(prefix="/api/v1/factors", tags=["factors"])


@router.get("", response_model=ApiResponse)
def get_factors(db: Session = Depends(get_db)):
    return ApiResponse.ok(serialize_factors(db))
