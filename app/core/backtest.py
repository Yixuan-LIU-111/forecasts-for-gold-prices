"""模拟交易回测（向量化实现，输出对齐 backtest.json 结构）。

基于历史信号或合成信号驱动，输出 summary/accuracy/equity_curve/
trade_details/pnl_distribution/hawk_dove_events，供 API 直接序列化。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, date, timezone
from typing import Optional
from uuid import uuid4

import numpy as np
import pandas as pd
from sqlalchemy import select, desc
from sqlalchemy.orm import Session

from app.models.database import MarketData, Signal, BacktestResult, HawkDoveEvent

logger = logging.getLogger(__name__)


def _to_naive(dt) -> datetime:
    """将 datetime 规范化为 naive（去掉时区），避免 tz-aware 与 naive 比较报错。"""
    if dt is None:
        return datetime.utcnow()
    if hasattr(dt, "tzinfo") and dt.tzinfo is not None:
        return dt.replace(tzinfo=None)
    return dt


def _to_date(val) -> Optional[date]:
    """把字符串/日期统一转成 date 对象（SQLite Date 列要求）。"""
    if val is None:
        return None
    if isinstance(val, datetime):
        return val.date()
    if isinstance(val, date):
        return val
    if isinstance(val, str):
        try:
            return datetime.strptime(val[:10], "%Y-%m-%d").date()
        except ValueError:
            return None
    return None


@dataclass
class BacktestParams:
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    initial_capital: float = 10000
    spread: float = 0.3
    commission_pct: float = 0.01
    signal_threshold: float = 0.55


def _load_price_series(db: Session) -> pd.DataFrame:
    stmt = (
        select(MarketData.timestamp, MarketData.price)
        .where(MarketData.symbol == "XAUUSD")
        .order_by(MarketData.timestamp)
    )
    rows = db.execute(stmt).all()
    if rows:
        df = pd.DataFrame(rows, columns=["timestamp", "price"])
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        return df
    return pd.DataFrame(columns=["timestamp", "price"])


def _load_signals(db: Session) -> list[Signal]:
    return list(
        db.execute(
            select(Signal).order_by(Signal.timestamp)
        ).scalars().all()
    )


def _simulate(
    prices: pd.DataFrame,
    signals: list[Signal],
    params: BacktestParams,
) -> dict:
    """向量化模拟交易。无数据时用合成结果兜底。"""
    if prices.empty or len(prices) < 10:
        return _synthetic_result(params)

    capital = params.initial_capital
    equity_curve = []
    trade_details = []
    position = 0  # 1 多, -1 空, 0 空
    entry_price = 0.0
    entry_prob = 0.0
    entry_idx = 0
    entry_qty = 0.0
    trade_id = 1
    threshold = params.signal_threshold
    max_hold = 6  # 最长持仓 K 线数，避免每根都开平仓

    # 动量代理概率的归一化尺度：用单根收益率的标准差，
    # 使 signal_threshold 在 (0,1) 全区间对开仓具有单调门控作用
    _rets = prices["price"].astype(float).pct_change().dropna()
    ret_std = float(_rets.std()) if len(_rets) > 1 else 0.0
    if not np.isfinite(ret_std) or ret_std <= 0:
        ret_std = 1e-6
    base_price = float(prices.iloc[0]["price"])
    ec_step = max(1, len(prices) // 60)  # 自适应采样，净值曲线约 60 个点

    def _signal_at(ts: datetime) -> Optional[Signal]:
        """取不晚于 ts 的最近一条信号（signals 已按时间升序）。"""
        found = None
        for s in signals:
            if _to_naive(s.timestamp) <= ts:
                found = s
            else:
                break
        return found

    for i in range(1, len(prices)):
        ts = _to_naive(prices.iloc[i]["timestamp"])
        price = float(prices.iloc[i]["price"])
        prev = float(prices.iloc[i - 1]["price"])
        ret = (price - prev) / prev if prev else 0.0

        # 方向判定：优先用最近信号；信号稀疏时用价格动量代理（均受阈值门控，
        # 使 signal_threshold / spread / commission 等参数真正影响结果）
        nearest_sig = _signal_at(ts)
        direction = None
        prob = 0.0
        if nearest_sig is not None:
            prob = float(nearest_sig.probability or 0.0)
            if nearest_sig.direction_en == "bullish" and prob >= threshold:
                direction = "bull"
            elif nearest_sig.direction_en == "bearish" and (1 - prob) >= threshold:
                direction = "bear"
                prob = 1 - prob
        else:
            prob = 0.5 + 0.49 * min(1.0, abs(ret) / (2.5 * ret_std))
            if prob >= threshold:
                direction = "bull" if ret > 0 else "bear"

        # 平仓：方向反转或达到最长持仓
        if position != 0:
            reversed_dir = direction is not None and (
                (direction == "bull" and position < 0) or (direction == "bear" and position > 0)
            )
            if reversed_dir or (i - entry_idx) >= max_hold or i == len(prices) - 1:
                exit_price = price
                # 成本：点差按价格单位计一次往返 + 佣金按名义金额双边收取
                cost_per_unit = params.spread + (entry_price + exit_price) * params.commission_pct / 100
                pnl = ((exit_price - entry_price) * position - cost_per_unit) * entry_qty
                pnl_pct = pnl / (entry_price * entry_qty) * 100 if entry_qty else 0.0
                trade_details.append({
                    "trade_id": trade_id,
                    "open_time": str(_to_naive(prices.iloc[entry_idx]["timestamp"])),
                    "direction": "看涨" if position > 0 else "看跌",
                    "open_price": round(entry_price, 2),
                    "close_time": str(ts),
                    "close_price": round(exit_price, 2),
                    "pnl": round(pnl, 2),
                    "pnl_pct": round(pnl_pct, 2),
                    "signal_prob": round(entry_prob, 2),
                })
                trade_id += 1
                capital += pnl
                position = 0

        # 开仓（1 倍名义仓位：qty = 可用资金 / 开仓价）
        if direction is not None and position == 0 and capital > 0:
            position = 1 if direction == "bull" else -1
            entry_price = price
            entry_prob = prob
            entry_idx = i
            entry_qty = capital / price

        # 记录净值
        if i % ec_step == 0 or i == len(prices) - 1:
            equity_curve.append({
                "date": str(ts.date()),
                "time": ts.strftime("%Y-%m-%d %H:%M"),
                "strategy": round(capital, 2),
                "benchmark": round(params.initial_capital * (price / base_price), 2),
            })

    # 有真实行情时不再退化为合成结果：即使阈值过高导致 0 笔交易，
    # 也如实返回真实模式的空结果，保证参数变化对前端可见
    return _assemble_result(
        trade_details,
        equity_curve,
        params,
        prices,
        final_capital=capital,
        data_mode="real",
    )


def _synthetic_result(params: BacktestParams) -> dict:
    """合成回测结果（无历史数据时的兜底）。"""
    rng = np.random.default_rng(7)
    n_trades = int(rng.integers(120, 200))
    start = params.start_date or "2026-04-30"
    end = params.end_date or "2026-07-29"

    trades = []
    capital = params.initial_capital
    for tid in range(1, n_trades + 1):
        direction = rng.choice(["看涨", "看跌", "观望"], p=[0.5, 0.4, 0.1])
        open_p = float(rng.uniform(2370, 2395))
        gross = float(rng.normal(2, 25)) if direction != "观望" else 0.0
        cost = (open_p + open_p) * params.spread * 0.01 + (open_p + open_p) * params.commission_pct * 0.01
        pnl = (gross - cost) if direction != "观望" else 0.0
        close_p = open_p + (pnl / 10 if direction != "观望" else 0)
        trades.append({
            "trade_id": tid,
            "open_time": f"2026-07-{20 + (tid % 9):02d} 10:{tid % 60:02d}",
            "direction": direction,
            "open_price": round(open_p, 2),
            "close_time": f"2026-07-{20 + (tid % 9):02d} 11:{tid % 60:02d}",
            "close_price": round(close_p, 2),
            "pnl": round(pnl, 2),
            "pnl_pct": round(pnl / open_p * 100, 2),
            "signal_prob": round(float(rng.uniform(0.55, 0.75)), 2),
        })
        capital += pnl

    weeks = 13
    equity_curve = []
    bench = params.initial_capital
    strat = params.initial_capital
    for w in range(weeks + 1):
        strat *= 1 + float(rng.normal(0.011, 0.015))
        bench *= 1 + float(rng.normal(0.005, 0.008))
        equity_curve.append({
            "date": f"2026-04-{30 + w * 7:02d}" if w == 0 else f"2026-{5 + (w * 7) // 30:02d}-{(w * 7) % 30:02d}",
            "strategy": round(strat, 2),
            "benchmark": round(bench, 2),
        })

    prices = pd.DataFrame()
    return _assemble_result(trades, equity_curve, params, prices, start, end, capital)


def _close_time(t: dict) -> Optional[datetime]:
    """解析交易的平仓时间，失败返回 None。"""
    raw = t.get("close_time")
    if not raw:
        return None
    try:
        return pd.to_datetime(raw).to_pydatetime().replace(tzinfo=None)
    except (ValueError, TypeError):
        return None


def _trades_within(trades: list[dict], days: int) -> list[dict]:
    """取最近 days 天内平仓的交易；时间不可解析时退化为全量。"""
    stamps = [ts for ts in (_close_time(t) for t in trades) if ts is not None]
    if not stamps:
        return list(trades)
    end = max(stamps)
    start = end - pd.Timedelta(days=days).to_pytimedelta()
    out = []
    for t in trades:
        ts = _close_time(t)
        if ts is None or ts >= start:
            out.append(t)
    return out


def _win_rate_within(trades: list[dict], days: int) -> float:
    sub = _trades_within(trades, days)
    if not sub:
        return 0.0
    return sum(1 for t in sub if t.get("pnl", 0) > 0) / len(sub) * 100


def _sample_within(trades: list[dict], days: int) -> int:
    return len(_trades_within(trades, days))


def _assemble_result(
    trades: list[dict],
    equity_curve: list[dict],
    params: BacktestParams,
    prices: pd.DataFrame,
    start: Optional[str] = None,
    end: Optional[str] = None,
    final_capital: Optional[float] = None,
    data_mode: str = "synthetic",
) -> dict:
    pnls = [t["pnl"] for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    total_return = (final_capital or params.initial_capital) - params.initial_capital
    total_return_pct = total_return / params.initial_capital * 100

    # 准确率（合成：基于交易胜率方向）
    win_rate = len(wins) / len(trades) * 100 if trades else 0
    bull_trades = [t for t in trades if t["direction"] == "看涨"]
    bear_trades = [t for t in trades if t["direction"] == "看跌"]
    bull_acc = (
        sum(1 for t in bull_trades if t["pnl"] > 0) / len(bull_trades) * 100
        if bull_trades else 0
    )
    bear_acc = (
        sum(1 for t in bear_trades if t["pnl"] > 0) / len(bear_trades) * 100
        if bear_trades else 0
    )

    # 盈亏分布
    bins = [-60, -40, -20, 0, 20, 40, 60]
    counts = [0] * (len(bins) - 1)
    for p in pnls:
        for b in range(len(bins) - 1):
            if bins[b] <= p < bins[b + 1]:
                counts[b] += 1
                break
        else:
            if p >= bins[-1]:
                counts[-1] += 1
            elif p < bins[0]:
                counts[0] += 1

    start_date = start or (str(prices.iloc[0]["timestamp"].date()) if not prices.empty else "2026-04-30")
    end_date = end or (str(prices.iloc[-1]["timestamp"].date()) if not prices.empty else "2026-07-29")
    final_cap = final_capital or (params.initial_capital + total_return)

    sharpe = round(np.mean(pnls) / (np.std(pnls) + 1e-9) * np.sqrt(len(trades)), 2) if pnls else 0
    # 基准收益率（买入持有）：优先用原始价格序列，其次退化到净值曲线
    benchmark_return_pct = 0.0
    if not prices.empty and len(prices) > 1:
        p0 = float(prices.iloc[0]["price"])
        p1 = float(prices.iloc[-1]["price"])
        benchmark_return_pct = (p1 / p0 - 1) * 100 if p0 else 0.0
    elif equity_curve:
        first_b = equity_curve[0].get("benchmark") or params.initial_capital
        last_b = equity_curve[-1].get("benchmark") or first_b
        benchmark_return_pct = (last_b / first_b - 1) * 100 if first_b else 0.0
    # 最大回撤：基于策略净值曲线，钳制到 [-100, 0]
    max_dd = 0.0
    if equity_curve:
        peak = equity_curve[0].get("strategy") or params.initial_capital
        for ec in equity_curve:
            v = ec.get("strategy") or peak
            if v > peak:
                peak = v
            dd = (v - peak) / peak * 100 if peak > 0 else 0
            if dd < max_dd:
                max_dd = dd
        max_dd = max(-100.0, max_dd)
    pl_ratio = round(
        (sum(wins) / len(wins)) / (abs(sum(losses) / len(losses)) if losses else 1), 2
    ) if wins and losses else 1.0

    return {
        "summary": {
            "total_return_pct": round(total_return_pct, 2),
            "annual_return_pct": round(total_return_pct * 4, 2),
            "sharpe_ratio": sharpe,
            "max_drawdown_pct": round(max_dd, 2),
            "benchmark_return_pct": round(benchmark_return_pct, 2),
            "data_mode": data_mode,
            "win_rate": round(win_rate, 2),
            "profit_loss_ratio": pl_ratio,
            "total_trades": len(trades),
            "start_date": start_date,
            "end_date": end_date,
            "initial_capital": params.initial_capital,
            "final_capital": round(final_cap, 2),
            "params": {
                "spread": params.spread,
                "commission_pct": params.commission_pct,
                "signal_threshold": params.signal_threshold,
            },
        },
        "accuracy": {
            # 按平仓时间切分滚动窗口真实统计，不再用「胜率 -4」这类拍脑袋数值
            "overall_7d": round(_win_rate_within(trades, 7), 2),
            "overall_30d": round(_win_rate_within(trades, 30), 2),
            "bullish_accuracy": round(bull_acc, 2),
            "bearish_accuracy": round(bear_acc, 2),
            "neutral_accuracy": 0,
            "sample_7d": _sample_within(trades, 7),
            "sample_30d": _sample_within(trades, 30),
            "sample_bullish": len(bull_trades),
            "sample_bearish": len(bear_trades),
            "data_mode": data_mode,
        },
        "equity_curve": equity_curve,
        "trade_details": trades,
        "pnl_distribution": {"bins": bins, "counts": counts},
    }


def run_backtest(db: Session, params: Optional[BacktestParams] = None) -> dict:
    """执行回测并持久化结果。返回完整结果 dict。"""
    if params is None:
        params = BacktestParams()

    prices = _load_price_series(db)
    signals = _load_signals(db)
    result = _simulate(prices, signals, params)

    # 补充鹰鸽事件
    events = list(
        db.execute(
            select(HawkDoveEvent).order_by(desc(HawkDoveEvent.date)).limit(20)
        ).scalars().all()
    )
    result["hawk_dove_events"] = [
        {
            "date": str(e.date),
            "speaker": e.speaker or "",
            "score": e.score or 0,
            "type": e.type or "dove",
            "label": e.label or "鸽派",
            "summary": e.summary or "",
        }
        for e in events
    ] or _default_hawk_dove_events()

    # 持久化
    bt = BacktestResult(
        run_id=str(uuid4()),
        start_date=_to_date(result["summary"]["start_date"]),
        end_date=_to_date(result["summary"]["end_date"]),
        summary=result["summary"],
        accuracy=result["accuracy"],
        equity_curve=result["equity_curve"],
        trade_details=result["trade_details"],
        pnl_distribution=result["pnl_distribution"],
        params=result["summary"]["params"],
    )
    db.add(bt)
    db.commit()
    return result


def _default_hawk_dove_events() -> list[dict]:
    return [
        {"date": "2026-07-24", "speaker": "鲍威尔", "score": 0.35, "type": "dove", "label": "鸽派", "summary": "暗示9月可能降息"},
        {"date": "2026-07-25", "speaker": "沃勒", "score": -0.42, "type": "hawk", "label": "鹰派", "summary": "通胀仍具粘性，不急于降息"},
        {"date": "2026-07-26", "speaker": "威廉姆斯", "score": 0.28, "type": "dove", "label": "鸽派", "summary": "经济数据支持温和政策"},
        {"date": "2026-07-27", "speaker": "鲍曼", "score": -0.15, "type": "hawk", "label": "鹰派", "summary": "需看到更多通胀进展"},
        {"date": "2026-07-28", "speaker": "戴利", "score": 0.10, "type": "dove", "label": "鸽派", "summary": "劳动力市场正在正常化"},
    ]


def get_latest_backtest(db: Session) -> Optional[dict]:
    """获取最近一次回测结果。"""
    bt = db.execute(
        select(BacktestResult).order_by(desc(BacktestResult.created_at), desc(BacktestResult.id)).limit(1)
    ).scalars().first()
    if bt is None:
        return None
    return {
        "summary": bt.summary,
        "accuracy": bt.accuracy,
        "equity_curve": bt.equity_curve,
        "trade_details": bt.trade_details,
        "pnl_distribution": bt.pnl_distribution,
        "hawk_dove_events": _default_hawk_dove_events(),
    }
