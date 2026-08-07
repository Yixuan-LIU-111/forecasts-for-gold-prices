"""AutoML —— 净化时序交叉验证 (Purged Walk-Forward CV) + 轻量超参搜索。

目标（对应需求：持续提升预测准确性与泛化能力）：
1. ** Purged Walk-Forward CV **
   沿时间轴把数据切成 n 个连续折，采用「扩张窗口」：第 f 折用 [0..f] 折训练、
   第 f+1 折测试；训练折内部再按时序切出验证集供早停。折与折之间施加
   López de Prado **purging**（丢弃验证/测试边界处会与训练标签重叠的 bar），
   避免标签泄漏。最终给出**无偏的泛化能力估计**（多折 AUC/Acc 的均值±标准差），
   而非单次切分的乐观估计。
2. ** Staged AutoML 调参 **
   以验证折集成 AUC 为目标，分阶段搜索关键超参（避免全网格爆炸）：
   lr×n_estimators → num_leaves/max_depth → subsample/colsample → reg_alpha/reg_lambda，
   每阶段在上阶段最优邻域细化，返回最优 LightGBM / XGBoost 联合参数。

所有切分严格时序、零前视；与现有 chronological_split / model 模块解耦复用。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from . import config
from . import model as M
from . import evaluate as EV
from .logging_setup import get_logger

logger = get_logger("thirty_min.automl")


# =================================================================== 参数映射
def joint_to_lgb(j: dict) -> dict:
    return {
        "objective": "binary",
        "metric": "binary_logloss",
        "num_leaves": int(j["num_leaves"]),
        "learning_rate": float(j["learning_rate"]),
        "n_estimators": int(j["n_estimators"]),
        "subsample": float(j["subsample"]),
        "colsample_bytree": float(j["colsample_bytree"]),
        "reg_alpha": float(j["reg_alpha"]),
        "reg_lambda": float(j["reg_lambda"]),
        "verbose": -1,
        "random_state": config.RANDOM_SEED,
        "n_jobs": -1,
    }


def joint_to_xgb(j: dict) -> dict:
    return {
        "objective": "binary:logistic",
        "max_depth": int(j["max_depth"]),
        "learning_rate": float(j["learning_rate"]),
        "n_estimators": int(j["n_estimators"]),
        "subsample": float(j["subsample"]),
        "colsample_bytree": float(j["colsample_bytree"]),
        "reg_alpha": float(j["reg_alpha"]),
        "reg_lambda": float(j["reg_lambda"]),
        "eval_metric": "logloss",
        "early_stopping_rounds": config.XGB_EARLY_STOPPING_ROUNDS,
        "random_state": config.RANDOM_SEED,
        "n_jobs": -1,
        "tree_method": "hist",
    }


def default_joint() -> dict:
    """与 config.LGB_PARAMS / XGB_PARAMS 等价的联合起点。"""
    return {
        "learning_rate": 0.05,
        "n_estimators": 300,
        "num_leaves": 31,
        "max_depth": 6,
        "subsample": 1.0,
        "colsample_bytree": 1.0,
        "reg_alpha": 0.0,
        "reg_lambda": 0.0,
    }


# =================================================================== 评估一次参数
def _eval_joint(Xtr, ytr, Xva, yva, joint: dict) -> dict:
    """训练 LGB+XGB（早停），返回验证集集成 AUC 与单模型 AUC。"""
    lgb_p = joint_to_lgb(joint)
    xgb_p = joint_to_xgb(joint)
    m_lgb = M.train_lightgbm(Xtr, ytr, Xva, yva, params=lgb_p)
    m_xgb = M.train_xgboost(Xtr, ytr, Xva, yva, params=xgb_p)
    p_l = m_lgb.predict_proba(Xva)[:, 1]
    p_x = m_xgb.predict_proba(Xva)[:, 1]
    p = M.ensemble_proba(p_l, p_x)
    try:
        auc = float(EV.compute_metrics(yva.to_numpy(), p)["auc"])
    except Exception:
        auc = float("nan")
    return {"auc": auc, "models": {"lgb": m_lgb, "xgb": m_xgb}}


# =================================================================== Purged Walk-Forward CV
def purged_walk_forward_cv(X, y, dates, n_folds: int = 4,
                           train_ratio_within: float = 0.85,
                           purge: int | None = None,
                           joint: dict | None = None,
                           return_folds: bool = False) -> dict:
    """扩张窗口净化 Walk-Forward CV。

    参数
    ----
    X, y, dates : 特征 / 标签 / 时间（已按时序）
    n_folds     : 连续折数（产生 n_folds-1 个测试窗口）
    purge       : 边界 purge 的 bar 数（默认 config.PURGE_BARS）
    joint       : 联合超参；None 用默认
    """
    if purge is None:
        purge = config.PURGE_BARS
    n = len(X)
    if n_folds < 3:
        n_folds = 3
    segs = [s for s in np.array_split(np.arange(n), n_folds) if len(s) > 0]
    joint = joint or default_joint()

    fold_records = []
    for f in range(len(segs) - 1):
        tr_block = np.concatenate(segs[: f + 1])
        te_block = segs[f + 1]
        # 训练折内再切验证集（时序）
        k = int(len(tr_block) * train_ratio_within)
        tr_idx = tr_block[: max(1, k)]
        va_idx = tr_block[k:]
        # purge：丢弃验证集边界与训练末根重叠的 bar
        if len(va_idx) > purge:
            va_idx = va_idx[purge:]
        Xtr, ytr = X.iloc[tr_idx], y.iloc[tr_idx]
        Xva, yva = X.iloc[va_idx], y.iloc[va_idx]
        Xte, yte = X.iloc[te_block], y.iloc[te_block]
        if len(Xva) == 0 or len(Xte) == 0:
            continue

        res = _eval_joint(Xtr, ytr, Xva, yva, joint)
        p_te = M.ensemble_proba(
            res["models"]["lgb"].predict_proba(Xte)[:, 1],
            res["models"]["xgb"].predict_proba(Xte)[:, 1],
        )
        m = EV.compute_metrics(yte.to_numpy(), p_te)
        rec = {
            "fold": f + 1,
            "n_train": int(len(Xtr)),
            "n_valid": int(len(Xva)),
            "n_test": int(len(Xte)),
            "test_auc": m["auc"],
            "test_accuracy": m["accuracy"],
            "test_f1": m["f1"],
            "test_logloss": m["logloss"],
            "test_pos_rate": m["pos_rate"],
        }
        fold_records.append(rec)
        logger.info("  WF 折 %d | n_tr=%d n_va=%d n_te=%d | AUC=%.4f Acc=%.4f",
                    rec["fold"], rec["n_train"], rec["n_valid"], rec["n_test"],
                    rec["test_auc"], rec["test_accuracy"])

    if not fold_records:
        return {"folds": [], "mean_auc": float("nan"), "std_auc": float("nan"),
                "mean_accuracy": float("nan"), "mean_f1": float("nan")}

    aucs = np.array([r["test_auc"] for r in fold_records], dtype=float)
    accs = np.array([r["test_accuracy"] for r in fold_records], dtype=float)
    f1s = np.array([r["test_f1"] for r in fold_records], dtype=float)
    out = {
        "folds": fold_records if return_folds else None,
        "n_folds": len(fold_records),
        "mean_auc": float(np.nanmean(aucs)),
        "std_auc": float(np.nanstd(aucs)),
        "min_auc": float(np.nanmin(aucs)),
        "max_auc": float(np.nanmax(aucs)),
        "mean_accuracy": float(np.nanmean(accs)),
        "std_accuracy": float(np.nanstd(accs)),
        "mean_f1": float(np.nanmean(f1s)),
    }
    logger.info("Walk-Forward 汇总：AUC=%.4f±%.4f (min=%.4f max=%.4f), Acc=%.4f±%.4f",
                out["mean_auc"], out["std_auc"], out["min_auc"], out["max_auc"],
                out["mean_accuracy"], out["std_accuracy"])
    return out


# =================================================================== Staged AutoML 调参
def automl_tune(Xtr, ytr, Xva, yva, base_joint: dict | None = None,
                max_evals: int = 24, verbose: bool = True) -> dict:
    """分阶段搜索最优联合超参，返回 {best_joint, best_auc, history}。

    阶段顺序（每阶段在上阶段最优邻域细化）：
      1) learning_rate × n_estimators
      2) num_leaves / max_depth（复杂度）
      3) subsample / colsample（采样）
      4) reg_alpha / reg_lambda（正则）
    """
    joint = (base_joint or default_joint()).copy()
    history: list[dict] = []

    def search(candidates: list[dict], stage: str):
        nonlocal joint
        best_local = None
        best_auc = -np.inf
        for c in candidates:
            cand = joint.copy()
            cand.update(c)
            try:
                r = _eval_joint(Xtr, ytr, Xva, yva, cand)
                auc = r["auc"]
            except Exception as e:
                logger.warning("  调参候选失败 %s: %s", c, e)
                auc = -np.inf
            history.append({"stage": stage, "params": cand, "val_auc": auc})
            if verbose:
                logger.info("  [%s] %s → val_auc=%.4f", stage,
                            {k: cand[k] for k in c}, auc)
            if auc > best_auc and np.isfinite(auc):
                best_auc, best_local = auc, cand
        if best_local is not None:
            joint = best_local
        return best_auc

    # 阶段 1：lr × n_est
    search([
        {"learning_rate": 0.03, "n_estimators": 300},
        {"learning_rate": 0.05, "n_estimators": 300},
        {"learning_rate": 0.08, "n_estimators": 200},
        {"learning_rate": 0.01, "n_estimators": 500},
    ], "lr_nest")

    # 阶段 2：复杂度
    nl = int(joint["num_leaves"])
    search([
        {"num_leaves": max(7, nl // 2), "max_depth": max(3, int(nl // 2).bit_length() + 1)},
        {"num_leaves": nl, "max_depth": int(np.log2(nl)) + 1 if nl > 1 else 3},
        {"num_leaves": min(127, nl * 2), "max_depth": min(10, int(np.log2(min(127, nl * 2))) + 2)},
    ], "complexity")

    # 阶段 3：采样
    search([
        {"subsample": 0.8, "colsample_bytree": 0.8},
        {"subsample": 1.0, "colsample_bytree": 1.0},
        {"subsample": 0.9, "colsample_bytree": 0.7},
    ], "sampling")

    # 阶段 4：正则
    search([
        {"reg_alpha": 0.0, "reg_lambda": 0.0},
        {"reg_alpha": 0.01, "reg_lambda": 0.01},
        {"reg_alpha": 0.1, "reg_lambda": 0.1},
    ], "regularization")

    best_auc = history[-1]["val_auc"] if history else float("nan")
    logger.info("AutoML 调参完成：最优 val_auc=%.4f，参数=%s", best_auc, joint)
    return {"best_joint": joint, "best_auc": best_auc, "history": history,
            "n_evals": len(history)}
