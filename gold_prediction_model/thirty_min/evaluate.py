"""评估 —— 准确率 / F1 / AUC / LogLoss + 基线对照 + 情感消融 + 收益回撤。

对应需求 4：划分训练/验证/测试集，给出准确率、收益回撤等指标，
并对比加入情感特征前后的效果（方案 §3.5 P0 消融）。
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.metrics import (
    accuracy_score, f1_score, log_loss, precision_score,
    recall_score, roc_auc_score, confusion_matrix,
)

from . import config
from . import model as M
from . import features as F
from .logging_setup import get_logger

logger = get_logger("thirty_min.eval")


# ------------------------------------------------------------------ 基础指标
def compute_metrics(y_true, p_pred, threshold: float = 0.5) -> dict:
    y_true = np.asarray(y_true).astype(int)
    p_pred = np.clip(np.asarray(p_pred, dtype=float), 1e-6, 1 - 1e-6)
    y_hat = (p_pred >= threshold).astype(int)
    try:
        auc = roc_auc_score(y_true, p_pred) if len(np.unique(y_true)) > 1 else float("nan")
    except ValueError:
        auc = float("nan")
    return {
        "accuracy": accuracy_score(y_true, y_hat),
        "f1": f1_score(y_true, y_hat, zero_division=0),
        "auc": auc,
        "logloss": log_loss(y_true, p_pred, labels=[0, 1]),
        "precision": precision_score(y_true, y_hat, zero_division=0),
        "recall": recall_score(y_true, y_hat, zero_division=0),
        "pos_rate": float(y_true.mean()),
    }


def baseline_metrics(y_train, y_test) -> dict:
    """基线对照：majority / always_up(买入持有) / prior。"""
    y_train = np.asarray(y_train).astype(int)
    y_test = np.asarray(y_test).astype(int)
    maj = int(round(y_train.mean()))
    prior = float(np.clip(y_train.mean(), 1e-6, 1 - 1e-6))
    return {
        "majority": compute_metrics(y_test, np.full(len(y_test), float(maj))),
        "always_up": compute_metrics(y_test, np.full(len(y_test), 1.0 - 1e-6)),
        "prior": compute_metrics(y_test, np.full(len(y_test), prior)),
        "_majority_class": maj,
        "_train_prior": prior,
        "_test_pos_rate": float(y_test.mean()),
    }


# ------------------------------------------------------------------ 时序划分（70/15/15 + purge）
def chronological_split(X, y, dates,
                        train_ratio=config.TRAIN_RATIO,
                        valid_ratio=config.VALID_RATIO,
                        purge=config.PURGE_BARS):
    n = len(X)
    i_tr = int(n * train_ratio)
    i_va = int(n * (train_ratio + valid_ratio))
    tr_end = max(0, i_tr - purge)
    va_end = max(tr_end, i_va - purge)

    def _sl(a, b):
        return (X.iloc[a:b], y.iloc[a:b], dates.iloc[a:b])

    return {
        "train": _sl(0, tr_end),
        "valid": _sl(i_tr, va_end),
        "test": _sl(i_va, n),
    }


# ------------------------------------------------------------------ 收益 / 回撤
def profit_drawdown(y_true, p_pred, returns: pd.Series | None = None,
                    long_th=config.SIGNAL_LONG_THRESHOLD,
                    short_th=config.SIGNAL_SHORT_THRESHOLD):
    """基于信号的简化策略回测（仅评估用，非生产回测）。

    规则：p>=long_th → 满仓多（下一窗口收益）；p<=short_th → 满仓空；
    其余 → 空仓（收益 0）。若未提供真实 returns（30 分钟收益率序列），
    则以真实方向 y_true 近似下一窗口符号收益。
    """
    p = np.asarray(p_pred, dtype=float)
    y = np.asarray(y_true).astype(int)
    n = len(p)
    position = np.where(p >= long_th, 1.0, np.where(p <= short_th, -1.0, 0.0))

    if returns is not None and len(returns) >= n:
        r = np.asarray(returns.iloc[:n], dtype=float)
    else:
        # 用方向近似：涨=+1 收益，跌=-1 收益（仅用于相对对比）
        r = np.where(y == 1, 1.0, -1.0) * 0.001

    strat_ret = position * r
    cum = np.cumprod(1 + strat_ret) - 1
    # 最大回撤
    equity = np.cumprod(1 + strat_ret)
    peak = np.maximum.accumulate(equity)
    dd = (equity - peak) / peak
    max_dd = float(dd.min())

    # 买入持有基准
    bh = np.cumprod(1 + r) - 1
    return {
        "strategy_cum_return": float(cum[-1]) if n else 0.0,
        "buyhold_cum_return": float(bh[-1]) if n else 0.0,
        "max_drawdown": max_dd,
        "n_signals": int((position != 0).sum()),
        "signal_coverage": float((position != 0).mean()),
    }


# ------------------------------------------------------------------ 情感消融对比
def run_ablation(df_featured: pd.DataFrame) -> dict:
    """同一份 30 分钟数据，分别训练「含情感」与「不含情感」两版，对比效果。

    返回结构化对比结果（含测试集指标、收益回撤、增量）。
    """
    X_all, y_all, dates_all, _ = F.make_xy(df_featured, "all")
    X_no, y_no, dates_no, _ = F.make_xy(df_featured, "no_sentiment")

    parts_all = chronological_split(X_all, y_all, dates_all)
    parts_no = chronological_split(X_no, y_no, dates_no)

    pred_all = {}
    pred_no = {}

    # 两个版本都基于各自 feature_set 的 train/valid 划分训练，仅特征集不同
    tr = parts_all["train"]; va = parts_all["valid"]; te = parts_all["test"]
    tr_n = parts_no["train"]; va_n = parts_no["valid"]; te_n = parts_no["test"]

    models_all = M.fit_dual_models(tr[0], tr[1], va[0], va[1])
    models_no = M.fit_dual_models(tr_n[0], tr_n[1], va_n[0], va_n[1])

    pred_all["y"] = te[1].to_numpy()
    pred_all["ensemble"] = M.ensemble_proba(
        models_all["lgb"].predict_proba(te[0])[:, 1],
        models_all["xgb"].predict_proba(te[0])[:, 1])
    pred_no["y"] = te_n[1].to_numpy()
    pred_no["ensemble"] = M.ensemble_proba(
        models_no["lgb"].predict_proba(te_n[0])[:, 1],
        models_no["xgb"].predict_proba(te_n[0])[:, 1])

    m_all = compute_metrics(pred_all["y"], pred_all["ensemble"])
    m_no = compute_metrics(pred_no["y"], pred_no["ensemble"])
    base = baseline_metrics(tr[1].to_numpy(), te[1].to_numpy())

    pd_all = profit_drawdown(pred_all["y"], pred_all["ensemble"])
    pd_no = profit_drawdown(pred_no["y"], pred_no["ensemble"])

    result = {
        "with_sentiment": {**m_all, **{"profit_drawdown": pd_all}},
        "without_sentiment": {**m_no, **{"profit_drawdown": pd_no}},
        "baseline": base,
        "delta_auc": m_all["auc"] - m_no["auc"],
        "delta_accuracy": m_all["accuracy"] - m_no["accuracy"],
        "conclusion": _ablation_conclusion(m_all["auc"], m_no["auc"]),
    }
    logger.info("消融完成：含情感 AUC=%.4f / 不含=%.4f / Δ=%.4f → %s",
                m_all["auc"], m_no["auc"], result["delta_auc"], result["conclusion"])
    return result


def _ablation_conclusion(auc_with: float, auc_without: float) -> str:
    delta = auc_with - auc_without
    if delta > 0.02:
        return "情感特征带来显著增量，建议进入模型精调"
    if auc_with < 0.53 and auc_without < 0.53:
        return "两版均无 distinguishable 预测力（AUC≈0.5），情感假设未成立；Demo 照常跑通，效果列为独立研究议题"
    return "情感增量有限，Demo 照常跑通；效果优化列为独立研究议题"
