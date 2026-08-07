"""Pydantic 响应模型（对齐 app/dashboard/demo_data/*.json）。

字段名、类型、嵌套与 demo_data 严格一致，确保 DEMO/LIVE 模式无缝切换。
时间字段统一用 str（ISO 8601），与 demo_data 保持一致。
"""
from __future__ import annotations

from typing import Optional, Any
from pydantic import BaseModel, Field


# ============================================================
# 信号
# ============================================================
class Attribution(BaseModel):
    factor: str
    value: float
    color: str  # green / red
    detail: str


class SignalOut(BaseModel):
    timestamp: str
    direction: str  # 看涨/看跌/观望
    direction_en: str  # bullish/bearish/neutral
    probability: float
    strength: int
    position: str  # 重仓/中仓/轻仓/观望
    position_pct: int
    bull_bear_score: int
    confidence: str  # 高/中/低
    confidence_value: int
    model: str
    attribution: list[Attribution]
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None


# ============================================================
# 行情
# ============================================================
class PricePoint(BaseModel):
    time: str
    price: float
    volume: int


class MarketOut(BaseModel):
    symbol: str
    current_price: float
    change: float
    change_pct: float
    high_24h: float
    low_24h: float
    open_24h: float
    prev_close: float
    timestamp: str
    prices: list[PricePoint]


# ============================================================
# 因子
# ============================================================
class FactorItem(BaseModel):
    name: str  # DXY/TIPS/VIX/GPR/sentiment/hawk_dove
    label: str
    value: float
    change: float
    change_pct: Optional[float] = None
    trend: str  # up/down/flat
    trend_color: str  # red/green/gray
    unit: str
    source: str


class FactorsOut(BaseModel):
    timestamp: str
    factors: list[FactorItem]


# ============================================================
# 新闻
# ============================================================
class NewsOut(BaseModel):
    id: str
    title: str
    title_zh: Optional[str] = None  # 中文概括标题，优先用于前端展示
    sentiment: str  # bullish/bearish/neutral
    sentiment_label: str  # 利多/利空/中性
    sentiment_score: float
    source: str
    published_at: str
    url: str
    confidence: float
    is_important: bool
    key_sentence: str
    topic: str
    hawk_dove: Optional[str] = None  # 鹰派/鸽派
    hawk_dove_score: Optional[float] = None


# ============================================================
# 回测
# ============================================================
class BacktestParams(BaseModel):
    spread: float = 0.3
    commission_pct: float = 0.01
    signal_threshold: float = 0.55


class BacktestSummary(BaseModel):
    total_return_pct: float
    annual_return_pct: float
    sharpe_ratio: float
    max_drawdown_pct: float
    win_rate: float
    profit_loss_ratio: float
    total_trades: int
    start_date: str
    end_date: str
    initial_capital: float
    final_capital: float
    params: BacktestParams
    benchmark_return_pct: Optional[float] = None
    data_mode: Optional[str] = None  # real / synthetic


class AccuracyOut(BaseModel):
    overall_7d: float
    overall_30d: float
    bullish_accuracy: float
    bearish_accuracy: float
    neutral_accuracy: float
    # 样本量：小样本时前端需给出可信度提示，避免「1 笔交易 100% 准确率」误导
    sample_7d: int = 0
    sample_30d: int = 0
    sample_bullish: int = 0
    sample_bearish: int = 0
    data_mode: Optional[str] = None


class EquityPoint(BaseModel):
    date: str
    time: Optional[str] = None
    strategy: float
    benchmark: float


class TradeDetail(BaseModel):
    trade_id: int
    open_time: str
    direction: str
    open_price: float
    close_time: str
    close_price: float
    pnl: float
    pnl_pct: float
    signal_prob: float


class PnlDistribution(BaseModel):
    bins: list[float]
    counts: list[int]


class HawkDoveEventOut(BaseModel):
    date: str
    speaker: str
    score: float  # 正=鸽派利好，负=鹰派利空
    type: str  # dove/hawk
    label: str  # 鸽派/鹰派
    summary: str


class BacktestOut(BaseModel):
    summary: BacktestSummary
    accuracy: AccuracyOut
    equity_curve: list[EquityPoint]
    trade_details: list[TradeDetail]
    pnl_distribution: PnlDistribution
    hawk_dove_events: list[HawkDoveEventOut]


class BacktestRunRequest(BaseModel):
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    initial_capital: float = 10000
    spread: float = 0.3
    commission_pct: float = 0.01
    signal_threshold: float = 0.55


# ============================================================
# 系统
# ============================================================
class ApiUsage(BaseModel):
    today: float = 0.0
    limit: float = 5.0
    name: str = "OpenAI"


class DataSourceOut(BaseModel):
    indicator_code: str
    indicator_name: str
    source_name: str
    source_url: Optional[str] = None
    update_frequency: str
    realtime: bool = True
    description: Optional[str] = None


class ModelInfoOut(BaseModel):
    name: str
    status: str  # loaded / synthetic_baseline / unavailable
    is_real_model: bool = False
    demo_mode: bool = True
    signal_threshold: float = 0.55
    available_indicators: list[str] = []


class SystemStatusOut(BaseModel):
    status: str  # ok/warning/error
    data_collection: str
    llm_service: str
    db_connection: str
    db_type: str = "SQLite"
    model_loaded: str
    model_info: Optional[ModelInfoOut] = None
    api_usage: ApiUsage
    timestamp: str
    mode: str  # 演示模式/实时模式


# ============================================================
# 统一响应封装
# ============================================================
class ApiResponse(BaseModel):
    code: int = 200
    message: str = "success"
    data: Optional[Any] = None

    @classmethod
    def ok(cls, data: Any) -> "ApiResponse":
        return cls(code=200, message="success", data=data)

    @classmethod
    def error(cls, code: int, message: str) -> "ApiResponse":
        return cls(code=code, message=message, data=None)
