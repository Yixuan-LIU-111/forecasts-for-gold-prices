"""模型层 —— LightGBM + XGBoost 加权集成（固定 30 分钟窗口）。

对齐《项目方案V2.0》§3.5：
- 双模型集成：p = 0.6·p_lgb + 0.4·p_xgb
- 早停指标改用 AUC（对正负先验偏移不敏感，避免 best_iteration=1 退化）
- Predictor 封装推理：输入一行特征 → 输出未来 30 分钟方向概率 + 置信度

工程要点：本模块全部相对导入，独立于旧日频模块的顶层 `import config`，
避免导入冲突（R4）。
"""

from __future__ import annotations

import joblib
import numpy as np
import pandas as pd

from . import config
from .logging_setup import get_logger

logger = get_logger("thirty_min.model")


# ------------------------------------------------------------------ 单模型
def train_lightgbm(X_tr, y_tr, X_va, y_va, params=None,
                   eval_metric: str = config.EARLY_STOP_METRIC_LGB):
    import lightgbm as lgb
    p = dict(config.LGB_PARAMS if params is None else params)
    model = lgb.LGBMClassifier(**p)
    model.fit(
        X_tr, y_tr,
        eval_X=X_va, eval_y=y_va,
        eval_metric=eval_metric,
        callbacks=[
            lgb.early_stopping(config.LGB_EARLY_STOPPING_ROUNDS, verbose=False),
            lgb.log_evaluation(0),
        ],
    )
    return model


def train_xgboost(X_tr, y_tr, X_va, y_va, params=None,
                 eval_metric: str = config.EARLY_STOP_METRIC_XGB):
    import xgboost as xgb
    p = dict(config.XGB_PARAMS if params is None else params)
    p["eval_metric"] = eval_metric
    p["early_stopping_rounds"] = config.XGB_EARLY_STOPPING_ROUNDS
    model = xgb.XGBClassifier(**p)
    model.fit(X_tr, y_tr, eval_set=[(X_va, y_va)], verbose=False)
    return model


def ensemble_proba(p_lgb: np.ndarray, p_xgb: np.ndarray) -> np.ndarray:
    """加权融合（方案 §9.4）：p_final = 0.6·p_lgb + 0.4·p_xgb"""
    return config.ENSEMBLE_W_LGB * np.asarray(p_lgb) + config.ENSEMBLE_W_XGB * np.asarray(p_xgb)


# ------------------------------------------------------------------ 组合训练
def fit_dual_models(X_tr, y_tr, X_va, y_va, lgb_params=None, xgb_params=None):
    """在 train 上拟合、valid 上早停，返回双模型。可接受 AutoML 调出的参数。"""
    m_lgb = train_lightgbm(X_tr, y_tr, X_va, y_va, params=lgb_params)
    m_xgb = train_xgboost(X_tr, y_tr, X_va, y_va, params=xgb_params)
    return {"lgb": m_lgb, "xgb": m_xgb}


# ------------------------------------------------------------------ Predictor 推理封装
class Predictor:
    """未来 30 分钟方向预测封装（可序列化、可热加载）。"""

    def __init__(self, models: dict | None = None, feature_cols: list[str] | None = None):
        self.models = models or {}
        self.feature_cols = feature_cols or []
        self.horizon_minutes = config.HORIZON_MINUTES
        self.predict_window = config.PREDICT_WINDOW

    # ---------------- 训练 ----------------
    def fit(self, X_tr, y_tr, X_va, y_va, lgb_params=None, xgb_params=None):
        self.models = fit_dual_models(X_tr, y_tr, X_va, y_va,
                                      lgb_params=lgb_params, xgb_params=xgb_params)
        self.feature_cols = list(X_tr.columns)
        return self

    # ---------------- 推理 ----------------
    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        """返回上涨概率（ensemble）。X 须含 self.feature_cols。"""
        Xs = X[self.feature_cols].astype(float)
        p_l = self.models["lgb"].predict_proba(Xs)[:, 1]
        p_x = self.models["xgb"].predict_proba(Xs)[:, 1]
        return ensemble_proba(p_l, p_x)

    def predict_direction(self, row: pd.DataFrame) -> dict:
        """对单行特征产出结构化预测（方案 §10.1 信号所需字段）。

        返回 dict：direction(涨/跌/观望)、direction_en、probability、
        confidence(0~1, |p-0.5|*2)、bull_bear_score、model 标识。
        """
        p = float(self.predict_proba(row.iloc[[0]])[0])
        conf = abs(p - 0.5) * 2.0
        if p >= config.SIGNAL_LONG_THRESHOLD:
            direction, en = "看涨", "bullish"
        elif p <= config.SIGNAL_SHORT_THRESHOLD:
            direction, en = "看跌", "bearish"
        else:
            direction, en = "观望", "neutral"
        return {
            "direction": direction,
            "direction_en": en,
            "probability": round(p, 4),
            "confidence": round(conf, 4),
            "bull_bear_score": round(p * 100, 1),
            "model": "LightGBM+XGBoost 加权",
            "predict_window": self.predict_window,
            "horizon_minutes": self.horizon_minutes,
        }

    # ---------------- 持久化 ----------------
    def save(self, tag: str = "primary"):
        paths = {}
        for name, m in self.models.items():
            p = config.ARTIFACT_DIR / f"{tag}_{name}.joblib"
            joblib.dump(m, p)
            paths[name] = str(p)
        meta = {
            "feature_cols": self.feature_cols,
            "horizon_minutes": self.horizon_minutes,
            "predict_window": self.predict_window,
            "ensemble_weights": {"lgb": config.ENSEMBLE_W_LGB, "xgb": config.ENSEMBLE_W_XGB},
            "paths": paths,
        }
        joblib.dump(meta, config.ARTIFACT_DIR / f"{tag}_meta.joblib")
        logger.info("模型已保存: %s", paths)
        return paths

    @classmethod
    def load(cls, tag: str = "primary") -> "Predictor":
        meta = joblib.load(config.ARTIFACT_DIR / f"{tag}_meta.joblib")
        models = {name: joblib.load(p) for name, p in meta["paths"].items()}
        return cls(models=models, feature_cols=meta["feature_cols"])
