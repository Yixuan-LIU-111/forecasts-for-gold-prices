"""模型训练 —— LightGBM 基线 + XGBoost 对比 + 加权融合。

严格对齐《项目方案V1.0.md》：
- §9.4  双模型超参、early_stopping_rounds=20、p_final = 0.6*p_lgb + 0.4*p_xgb
- §9.5  70/15/15 时间顺序划分、Walk-Forward 验证、joblib 序列化
"""

from __future__ import annotations

import warnings

import joblib
import lightgbm as lgb
import numpy as np
import pandas as pd
import xgboost as xgb

import config as C
import features as F

warnings.filterwarnings("ignore", category=UserWarning)


# ------------------------------------------------------------------ 单模型
def train_lightgbm(X_tr, y_tr, X_va, y_va, params: dict | None = None,
                   eval_metric: str = C.EARLY_STOP_METRIC_LGB):
    """LightGBM 基线模型（文档 §9.4）。

    early stopping 指标默认用 AUC 而非 binary_logloss：
    验证段正类占比(79%)与训练段(52%)差异极大，logloss 受先验偏移主导，
    会在第 1 轮就触发早停（实测 best_iteration=1，模型完全没学到东西）。
    AUC 是基于排序的指标，对先验偏移不敏感，能反映真实判别力。
    """
    p = dict(C.LGB_PARAMS if params is None else params)
    model = lgb.LGBMClassifier(**p)
    model.fit(
        X_tr, y_tr,
        eval_set=[(X_va, y_va)],
        eval_metric=eval_metric,
        callbacks=[
            lgb.early_stopping(C.LGB_EARLY_STOPPING_ROUNDS, verbose=False),
            lgb.log_evaluation(0),
        ],
    )
    return model


def train_xgboost(X_tr, y_tr, X_va, y_va, params: dict | None = None,
                  eval_metric: str = C.EARLY_STOP_METRIC_XGB):
    """XGBoost 对比模型（文档 §9.4）。

    注：XGBoost >=2.0 起 early_stopping_rounds 移至构造函数，
    此处按新版 API 传参，行为与文档描述一致。
    早停指标同样改用 AUC，原因见 train_lightgbm 说明。
    """
    p = dict(C.XGB_PARAMS if params is None else params)
    p["eval_metric"] = eval_metric
    p["early_stopping_rounds"] = C.XGB_EARLY_STOPPING_ROUNDS
    model = xgb.XGBClassifier(**p)
    model.fit(X_tr, y_tr, eval_set=[(X_va, y_va)], verbose=False)
    return model


def ensemble_proba(p_lgb: np.ndarray, p_xgb: np.ndarray) -> np.ndarray:
    """加权融合（文档 §9.4）：p_final = 0.6*p_lgb + 0.4*p_xgb"""
    return C.ENSEMBLE_W_LGB * p_lgb + C.ENSEMBLE_W_XGB * p_xgb


# ------------------------------------------------------------------ 组合训练
def fit_dual_models(parts, lgb_params=None, xgb_params=None):
    """在 train 上拟合、valid 上早停，返回双模型与各切片概率。"""
    X_tr, y_tr, _ = parts["train"]
    X_va, y_va, _ = parts["valid"]

    m_lgb = train_lightgbm(X_tr, y_tr, X_va, y_va, lgb_params)
    m_xgb = train_xgboost(X_tr, y_tr, X_va, y_va, xgb_params)

    proba = {}
    for split, (Xs, ys, ds) in parts.items():
        p_l = m_lgb.predict_proba(Xs)[:, 1]
        p_x = m_xgb.predict_proba(Xs)[:, 1]
        proba[split] = {
            "lgb": p_l,
            "xgb": p_x,
            "ensemble": ensemble_proba(p_l, p_x),
            "y": ys.to_numpy(),
            "dates": ds.reset_index(drop=True),
        }
    return {"lgb": m_lgb, "xgb": m_xgb}, proba


# ------------------------------------------------------------------ Walk-Forward
def walk_forward(X, y, dates, n_splits: int = C.WALK_FORWARD_SPLITS,
                 lgb_params=None, xgb_params=None):
    """Walk-Forward 滚动验证（文档 §9.5，防特征泄露）。

    扩张窗口：第 k 折用前 k 段做训练+验证，紧随其后的一段做测试，
    训练区间永远早于测试区间，严格保持时间边界。
    """
    from evaluate import compute_metrics  # 延迟导入避免循环依赖

    n = len(X)
    fold_size = n // (n_splits + 1)
    rows = []

    for k in range(1, n_splits + 1):
        end_tr = fold_size * k
        end_te = fold_size * (k + 1) if k < n_splits else n

        # 训练段内部再切出 15% 作早停验证集（仍按时间顺序）
        cut = int(end_tr * 0.85)
        if cut < 50 or end_tr - cut < 10:
            continue

        sub = {
            "train": (X.iloc[:cut], y.iloc[:cut], dates.iloc[:cut]),
            "valid": (X.iloc[cut:end_tr], y.iloc[cut:end_tr], dates.iloc[cut:end_tr]),
            "test": (X.iloc[end_tr:end_te], y.iloc[end_tr:end_te], dates.iloc[end_tr:end_te]),
        }
        if len(sub["test"][0]) < 10:
            continue

        _, proba = fit_dual_models(sub, lgb_params, xgb_params)
        te = proba["test"]
        m = compute_metrics(te["y"], te["ensemble"])
        m.update({
            "fold": k,
            "train_end": sub["train"][2].iloc[-1].date(),
            "test_start": sub["test"][2].iloc[0].date(),
            "test_end": sub["test"][2].iloc[-1].date(),
            "n_test": len(te["y"]),
        })
        rows.append(m)

    return pd.DataFrame(rows)


# ------------------------------------------------------------------ 无早停拟合
def fit_fixed(X_tr, y_tr, lgb_params=None, xgb_params=None,
              n_est_lgb: int = 100, n_est_xgb: int = 100):
    """用固定树数拟合（不做早停）。

    早停依赖一个连续的验证块，而本数据集验证块与训练块处于完全不同的
    市场状态（正类占比 52% vs 79%），导致早停在第 1 轮即触发、模型退化为
    单个树桩。正确做法是：用 purged walk-forward CV 在开发集内部确定树数，
    再用该树数在整个开发集上无早停拟合。
    """
    lp = dict(C.LGB_PARAMS if lgb_params is None else lgb_params)
    xp = dict(C.XGB_PARAMS if xgb_params is None else xgb_params)
    lp["n_estimators"] = max(1, int(n_est_lgb))
    xp["n_estimators"] = max(1, int(n_est_xgb))
    xp.pop("early_stopping_rounds", None)

    m_lgb = lgb.LGBMClassifier(**lp).fit(X_tr, y_tr)
    m_xgb = xgb.XGBClassifier(**xp).fit(X_tr, y_tr, verbose=False)
    return {"lgb": m_lgb, "xgb": m_xgb}


def purged_cv_score(X, y, lgb_params=None, xgb_params=None,
                    n_splits: int = 4, purge: int = C.PURGE_BARS,
                    n_est_grid=(50, 100, 200, 400)):
    """开发集内部的 purged walk-forward CV，返回 (最优树数, 平均CV AUC)。

    严格只使用开发集（train+valid），测试集全程不参与，杜绝选择性泄露。
    每折训练段与验证段之间剔除 `purge` 根 bar，切断标签窗口重叠。
    """
    from evaluate import compute_metrics

    n = len(X)
    fold = n // (n_splits + 1)
    results = {ne: [] for ne in n_est_grid}

    for k in range(1, n_splits + 1):
        end_tr = fold * k
        end_va = fold * (k + 1) if k < n_splits else n
        tr_end = max(0, end_tr - purge)
        if tr_end < 100 or end_va - end_tr < 20:
            continue

        Xtr, ytr = X.iloc[:tr_end], y.iloc[:tr_end]
        Xva, yva = X.iloc[end_tr:end_va], y.iloc[end_tr:end_va]
        if yva.nunique() < 2:
            continue

        for ne in n_est_grid:
            ms = fit_fixed(Xtr, ytr, lgb_params, xgb_params, ne, ne)
            p = ensemble_proba(ms["lgb"].predict_proba(Xva)[:, 1],
                               ms["xgb"].predict_proba(Xva)[:, 1])
            results[ne].append(compute_metrics(yva, p)["auc"])

    means = {ne: float(np.nanmean(v)) for ne, v in results.items() if v}
    if not means:
        return 100, float("nan")
    best_ne = max(means, key=means.get)
    return best_ne, means[best_ne]


# ------------------------------------------------------------------ 持久化
def save_models(models: dict, feature_cols: list[str], tag: str = "primary"):
    """joblib 序列化（文档 §9.5：模型文件 joblib 序列化，本地存储）。"""
    paths = {}
    for name, model in models.items():
        p = C.ARTIFACT_DIR / f"{tag}_{name}.joblib"
        joblib.dump(model, p)
        paths[name] = str(p)

    meta = {
        "feature_cols": feature_cols,
        "horizon": C.HORIZON,
        "roll_window": C.ROLL_WINDOW,
        "ensemble_weights": {"lgb": C.ENSEMBLE_W_LGB, "xgb": C.ENSEMBLE_W_XGB},
        "paths": paths,
    }
    joblib.dump(meta, C.ARTIFACT_DIR / f"{tag}_meta.joblib")
    return paths


def feature_importance(models: dict, feature_cols: list[str]) -> pd.DataFrame:
    """特征重要性归因（文档 §10.5：用 LightGBM 特征重要性替代 SHAP）。"""
    imp = pd.DataFrame({"feature": feature_cols})
    imp["lgb_gain"] = models["lgb"].booster_.feature_importance(importance_type="gain")
    imp["xgb_gain"] = models["xgb"].feature_importances_

    for c in ("lgb_gain", "xgb_gain"):
        s = imp[c].sum()
        imp[c + "_pct"] = imp[c] / s * 100 if s > 0 else 0.0

    imp = imp.sort_values("lgb_gain", ascending=False).reset_index(drop=True)
    return imp
