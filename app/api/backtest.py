"""回测相关端点（4 个）。"""
from fastapi import APIRouter, Depends
from sqlalchemy import select, desc
from sqlalchemy.orm import Session

from app.models.database import get_db, BacktestResult
from app.models.schemas import ApiResponse, BacktestRunRequest
from app.api.deps import serialize_trades, serialize_pnl, serialize_hawk_dove_events
from app.core.backtest import run_backtest, BacktestParams

router = APIRouter(prefix="/api/v1/backtest", tags=["backtest"])


def _get_full(db: Session) -> dict:
    bt = db.execute(
        select(BacktestResult).order_by(desc(BacktestResult.created_at), desc(BacktestResult.id)).limit(1)
    ).scalars().first()
    if bt is None:
        return run_backtest(db, BacktestParams())
    return {
        "summary": bt.summary,
        "accuracy": bt.accuracy,
        "equity_curve": bt.equity_curve,
        "trade_details": bt.trade_details,
        "pnl_distribution": bt.pnl_distribution,
        "hawk_dove_events": serialize_hawk_dove_events(db),
    }


@router.get("/results", response_model=ApiResponse)
def get_backtest_results(db: Session = Depends(get_db)):
    return ApiResponse.ok(_get_full(db))


@router.post("/run", response_model=ApiResponse)
def run_backtest_endpoint(
    params: BacktestRunRequest = None,
    db: Session = Depends(get_db),
):
    p = params or BacktestRunRequest()
    # 参数校验（统一错误信封，避免 422 裸异常）
    errs = []
    if p.initial_capital <= 0:
        errs.append("初始资金必须大于 0")
    if not (0 <= p.spread <= 10):
        errs.append("点差需在 0~10 USD 之间")
    if not (0 <= p.commission_pct <= 0.1):
        errs.append("手续费率需在 0~10% 之间")
    if not (0 < p.signal_threshold < 1):
        errs.append("信号阈值需在 0~1 之间")
    if errs:
        return ApiResponse.error(422, "；".join(errs))

    bp = BacktestParams(
        start_date=p.start_date,
        end_date=p.end_date,
        initial_capital=p.initial_capital,
        spread=p.spread,
        commission_pct=p.commission_pct,
        signal_threshold=p.signal_threshold,
    )
    result = run_backtest(db, bp)
    return ApiResponse.ok(result)


@router.get("/pnl-distribution", response_model=ApiResponse)
def get_pnl_distribution(db: Session = Depends(get_db)):
    return ApiResponse.ok(serialize_pnl(db))


@router.get("/trades", response_model=ApiResponse)
def get_trade_details(db: Session = Depends(get_db)):
    return ApiResponse.ok(serialize_trades(db))
