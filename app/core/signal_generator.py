"""信号生成器（对齐项目方案 10.1）。

输入：模型概率 + 6 因子数据 + 当前价格
输出：Signal ORM 对象（字段对齐前端 signals.json），含 6 因子归因。
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.core.feature_engineer import build_features, load_latest_factors
from app.core.predictor import WeightedPredictor
from app.models.database import Signal

logger = logging.getLogger(__name__)

MODEL_NAME = "LightGBM+XGBoost 加权"


def _confidence_value(probability: float, factors: dict) -> int:
    """置信度数值 0~100：概率偏离 0.5 越多 + 因子方向一致，置信度越高。"""
    base = abs(probability - 0.5) * 100  # 0~50
    # 因子一致性加分
    sent = factors.get("sentiment", {}).get("value", 0) or 0
    hd = factors.get("hawk_dove", {}).get("value", 0) or 0
    consistency = 0
    if (probability > 0.5 and sent > 0) or (probability < 0.5 and sent < 0):
        consistency += 15
    if (probability > 0.5 and hd < 0) or (probability < 0.5 and hd > 0):
        consistency += 10
    return int(max(20, min(95, 50 + base + consistency)))


def _confidence_label(value: int) -> str:
    if value >= 75:
        return "高"
    if value >= 55:
        return "中"
    return "低"


def _rules(prob: float, conf: int) -> tuple[str, str, int, str]:
    """返回 (direction_en, position, position_pct, direction_cn)。"""
    if prob > 0.70 and conf > 70:
        return "bullish", "重仓", 80, "看涨"
    if prob > 0.60 and conf > 55:
        return "bullish", "中仓", 50, "看涨"
    if prob < 0.30 and conf > 70:
        return "bearish", "重仓", 80, "看跌"
    if prob < 0.40 and conf > 55:
        return "bearish", "中仓", 50, "看跌"
    return "neutral", "观望", 0, "观望"


def _anti_jitter(
    direction_en: str, position: str, position_pct: int, vix: float, db: Session
) -> tuple[str, str, int]:
    """防抖：高波动降级；连续反转转观望。"""
    if vix > 40:
        grade = {"重仓": "中仓", "中仓": "轻仓", "轻仓": "轻仓", "观望": "观望"}
        position = grade.get(position, position)
        position_pct = {"重仓": 50, "中仓": 25, "轻仓": 25, "观望": 0}.get(position, position_pct)

    # 连续 3 次方向反转 → 观望
    from sqlalchemy import select, desc

    recent = db.execute(
        select(Signal.direction_en).order_by(desc(Signal.timestamp)).limit(3)
    ).scalars().all()
    if len(recent) >= 3 and len(set(recent)) >= 2:
        flips = sum(1 for i in range(len(recent) - 1) if recent[i] != recent[i + 1])
        if flips >= 2 and direction_en != recent[0]:
            return "neutral", "观望", 0
    return direction_en, position, position_pct


def _build_attribution(factors: dict, direction_en: str) -> list[dict]:
    """生成 6 因子归因数组（对齐前端 attribution 字段）。"""
    sign = 1 if direction_en == "bullish" else (-1 if direction_en == "bearish" else 0)
    out = []

    def add(factor: str, value: float, color: str, detail: str):
        out.append({"factor": factor, "value": round(value, 3), "color": color, "detail": detail})

    # 新闻情感
    sent = factors.get("sentiment", {}).get("value", 0) or 0
    sent_change = factors.get("sentiment", {}).get("change", 0) or 0
    trend = "上升" if sent_change > 0 else ("下降" if sent_change < 0 else "持平")
    add("新闻情感", sent * 0.8 if sent != 0 else sign * 0.1, "green" if sent >= 0 else "red",
        f"最新值: {sent:+.2f}, 趋势: {trend}")

    # 鹰鸽指数
    hd = factors.get("hawk_dove", {}).get("value", 0) or 0
    hd_label = "鸽派" if hd < 0 else ("鹰派" if hd > 0 else "中性")
    add("鹰鸽指数", -hd * 0.8 if hd != 0 else sign * 0.1, "green" if hd <= 0 else "red",
        f"最新值: {hd:+.2f}, 趋势: {hd_label}")

    # DXY（上涨利空）
    dxy = factors.get("DXY", {}).get("value", 0) or 0
    dxy_ret = factors.get("DXY", {}).get("change", 0) or 0
    dxy_trend = "上涨(利空)" if dxy_ret > 0 else ("下跌(利好)" if dxy_ret < 0 else "持平")
    contrib = -0.15 if dxy_ret > 0 else (0.15 if dxy_ret < 0 else 0)
    add("DXY", contrib, "red" if dxy_ret > 0 else "green", f"最新值: {dxy:.2f}, 趋势: {dxy_trend}")

    # TIPS（上升利空）
    tips = factors.get("TIPS10Y", {}).get("value", 0) or 0
    tips_chg = factors.get("TIPS10Y", {}).get("change", 0) or 0
    tips_trend = "下跌(利好)" if tips_chg < 0 else ("上升(利空)" if tips_chg > 0 else "持平")
    contrib = -0.08 if tips_chg > 0 else (0.08 if tips_chg < 0 else 0)
    add("TIPS", contrib, "red" if tips_chg > 0 else "green", f"最新值: {tips:.2f}%, 趋势: {tips_trend}")

    # VIX
    vix = factors.get("VIX", {}).get("value", 0) or 0
    vix_chg = factors.get("VIX", {}).get("change", 0) or 0
    vix_trend = "持平" if abs(vix_chg) < 0.1 else ("上升" if vix_chg > 0 else "下降")
    add("VIX", 0.05 if vix > 20 else 0.03, "green", f"最新值: {vix:.2f}, 趋势: {vix_trend}")

    # GPR（上升利多避险，但高值标记利空）
    gpr = factors.get("GPR", {}).get("value", 0) or 0
    gpr_chg = factors.get("GPR", {}).get("change", 0) or 0
    gpr_trend = "上升(利空)" if gpr_chg > 0 else ("下降(利好)" if gpr_chg < 0 else "持平")
    add("GPR", -0.03 if gpr_chg > 0 else 0.03, "red" if gpr_chg > 0 else "green",
        f"最新值: {gpr:.2f}, 趋势: {gpr_trend}")

    return out


def generate_signal(db: Session, model: Optional[WeightedPredictor] = None) -> Optional[Signal]:
    """生成并持久化一个信号。"""
    feats = build_features(db)
    if feats.empty:
        logger.warning("特征为空，无法生成信号")
        return None

    if model is None:
        model = WeightedPredictor.load()

    prob = model.predict_proba(feats)
    factors = load_latest_factors(db)
    conf_val = _confidence_value(prob, factors)
    conf_label = _confidence_label(conf_val)

    direction_en, position, position_pct, direction_cn = _rules(prob, conf_val)
    vix = factors.get("VIX", {}).get("value", 0) or 0
    direction_en, position, position_pct = _anti_jitter(
        direction_en, position, position_pct, vix, db
    )
    if direction_en == "neutral":
        direction_cn, position = "观望", "观望"
        position_pct = 0

    # 多空评分 0~100
    bull_bear_score = int(max(0, min(100, 50 + (prob - 0.5) * 80)))

    # 止损/止盈
    price = float(feats.iloc[0].get("price", 0))
    stop_loss = take_profit = None
    if direction_en != "neutral" and price > 0:
        if direction_en == "bullish":
            stop_loss = round(price * (1 - 0.003), 2)
            take_profit = round(price * (1 + 0.006), 2)
        else:
            stop_loss = round(price * (1 + 0.003), 2)
            take_profit = round(price * (1 - 0.006), 2)

    attribution = _build_attribution(factors, direction_en)

    sig = Signal(
        timestamp=datetime.now(timezone.utc),
        direction=direction_cn,
        direction_en=direction_en,
        probability=round(prob, 4),
        strength=bull_bear_score,
        position=position,
        position_pct=position_pct,
        bull_bear_score=bull_bear_score,
        confidence=conf_label,
        confidence_value=conf_val,
        model=MODEL_NAME,
        attribution=attribution,
        news_refs=None,
        stop_loss=stop_loss,
        take_profit=take_profit,
    )
    db.add(sig)
    db.commit()
    db.refresh(sig)
    logger.info(
        "信号生成: %s prob=%.3f strength=%d position=%s",
        direction_cn, prob, bull_bear_score, position,
    )
    return sig


# ============================================================
# 以下为当前项目原有辅助函数，向后兼容保留（供前端 / API 读取最近一条信号）。
# ============================================================
def latest_signal(db: Session) -> Optional[dict]:
    """读取最近一条信号（供前端 / API 使用）。

    兼容当前项目旧字段 factors / news_refs，同时附带 main 的 attribution。
    """
    from sqlalchemy import select, desc

    sig = db.execute(
        select(Signal).order_by(desc(Signal.timestamp)).limit(1)
    ).scalars().first()
    if sig is None:
        return None
    return {
        "timestamp": sig.timestamp.isoformat() if sig.timestamp else None,
        "direction": sig.direction,
        "direction_en": sig.direction_en,
        "probability": float(sig.probability) if sig.probability is not None else None,
        "strength": sig.strength,
        "position": sig.position,
        "position_pct": sig.position_pct,
        "bull_bear_score": sig.bull_bear_score,
        "confidence": sig.confidence,
        "confidence_value": sig.confidence_value,
        "model": sig.model,
        "attribution": sig.attribution,
        "factors": sig.factors,
        "news_refs": sig.news_refs,
        "stop_loss": sig.stop_loss,
        "take_profit": sig.take_profit,
    }
