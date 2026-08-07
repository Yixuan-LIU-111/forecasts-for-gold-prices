"""API 路由层：12 个 RESTful 端点（对齐前端 client.py 12 函数）。"""
from app.api.deps import (
    ApiResponse,
    serialize_signal,
    serialize_market,
    serialize_factors,
    serialize_news,
    serialize_accuracy,
    serialize_pnl,
    serialize_trades,
    serialize_hawk_dove_events,
    range_hours_to_period,
)

__all__ = [
    "ApiResponse",
    "serialize_signal",
    "serialize_market",
    "serialize_factors",
    "serialize_news",
    "serialize_accuracy",
    "serialize_pnl",
    "serialize_trades",
    "serialize_hawk_dove_events",
    "range_hours_to_period",
]
