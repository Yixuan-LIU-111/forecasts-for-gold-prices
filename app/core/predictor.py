"""时序预测模型（LightGBM + XGBoost 加权）。

提供训练与推理能力。无训练数据/模型文件时降级为因子加权启发式，
保证信号生成链路可用。
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from app.config import MODELS_DIR
from app.core.feature_engineer import get_feature_columns

logger = logging.getLogger(__name__)

MODEL_PATH = MODELS_DIR / "predictor.joblib"
_FEATURES = get_feature_columns()


class WeightedPredictor:
    """LightGBM + XGBoost 加权集成。权重默认 0.6/0.4。"""

    def __init__(self):
        self.lgb = None
        self.xgb = None
        self.w_lgb = 0.6
        self.w_xgb = 0.4
        self.trained = False

    def train(self, X: pd.DataFrame, y: pd.Series) -> None:
        """训练双模型。"""
        try:
            import lightgbm as lgb
            import xgboost as xgb

            self.lgb = lgb.LGBMClassifier(
                n_estimators=100, max_depth=5, learning_rate=0.1, verbose=-1
            )
            self.lgb.fit(X, y)

            self.xgb = xgb.XGBClassifier(
                n_estimators=100, max_depth=5, learning_rate=0.1, verbosity=0
            )
            self.xgb.fit(X, y)
            self.trained = True
            logger.info("双模型训练完成，样本数=%d", len(y))
        except Exception as e:  # noqa: BLE001
            logger.warning("模型训练失败: %s", e)
            self.trained = False

    def predict_proba(self, X: pd.DataFrame) -> float:
        """返回上涨概率。"""
        if not self.trained or self.lgb is None or self.xgb is None:
            return _heuristic_proba(X)
        try:
            p_lgb = float(self.lgb.predict_proba(X)[0, 1])
            p_xgb = float(self.xgb.predict_proba(X)[0, 1])
            return round(self.w_lgb * p_lgb + self.w_xgb * p_xgb, 4)
        except Exception as e:  # noqa: BLE001
            logger.warning("模型推理异常，降级启发式: %s", e)
            return _heuristic_proba(X)

    def save(self, path: Path = MODEL_PATH) -> None:
        if not self.trained:
            return
        try:
            import joblib

            joblib.dump(
                {"lgb": self.lgb, "xgb": self.xgb, "w_lgb": self.w_lgb, "w_xgb": self.w_xgb},
                path,
            )
            logger.info("模型已保存到 %s", path)
        except Exception as e:  # noqa: BLE001
            logger.warning("模型保存失败: %s", e)

    @classmethod
    def load(cls, path: Path = MODEL_PATH) -> "WeightedPredictor":
        p = cls()
        if not path.exists():
            logger.info("无已训练模型，推理将使用因子启发式")
            return p
        try:
            import joblib

            data = joblib.load(path)
            p.lgb = data["lgb"]
            p.xgb = data["xgb"]
            p.w_lgb = data["w_lgb"]
            p.w_xgb = data["w_xgb"]
            p.trained = True
            logger.info("已加载模型 %s", path)
        except Exception as e:  # noqa: BLE001
            logger.warning("模型加载失败: %s", e)
        return p


def _heuristic_proba(X: pd.DataFrame) -> float:
    """因子加权启发式（降级方案）。

    基于因子方向合成上涨概率，保证无模型时仍可输出合理信号。
    """
    row = X.iloc[0].to_dict() if not X.empty else {}
    score = 0.5
    # 情感利多 +0.1，鹰鸽鸽派利多 +0.08
    score += max(-0.1, min(0.1, row.get("sentiment_score", 0) * 0.15))
    score += max(-0.08, min(0.08, -row.get("hawkish_score", 0) * 0.1))
    # DXY 上涨利空
    score -= max(-0.08, min(0.08, row.get("dxy_return", 0) * 0.05))
    # TIPS 上升利空
    score -= max(-0.06, min(0.06, row.get("tips_change", 0) * 0.03))
    # VIX 高位略偏多（避险）
    if row.get("vix", 0) > 25:
        score += 0.04
    # 动量
    score += max(-0.05, min(0.05, row.get("momentum_5m", 0) * 2))
    return round(max(0.05, min(0.95, float(score))), 4)


def train_synthetic_model(db=None, n_samples: int = 2000) -> WeightedPredictor:
    """用合成数据训练一个基线模型（无历史数据时的冷启动）。

    合成规则：基于因子方向构造概率标签，使模型学到合理的因子关系。
    """
    rng = np.random.default_rng(42)
    data = []
    labels = []
    for _ in range(n_samples):
        row = {
            "price": rng.uniform(2300, 2450),
            "return_30min": rng.normal(0, 0.005),
            "volatility_30min": abs(rng.normal(0, 0.003)),
            "momentum_5m": rng.normal(0, 0.002),
            "momentum_10m": rng.normal(0, 0.003),
            "dxy": rng.uniform(99, 105),
            "dxy_return": rng.normal(0, 0.003),
            "tips_yield": rng.uniform(1.8, 2.8),
            "tips_change": rng.normal(0, 0.05),
            "vix": rng.uniform(12, 35),
            "vix_high_vol": 0,
            "gpr_score": rng.uniform(150, 250),
            "gpr_event_flag": 0,
            "sentiment_score": rng.uniform(-0.6, 0.6),
            "hawkish_score": rng.uniform(-0.5, 0.5),
            "news_count_recent": int(rng.integers(0, 20)),
        }
        row["vix_high_vol"] = 1 if row["vix"] > 30 else 0
        row["gpr_event_flag"] = 1 if row["gpr_score"] > 200 else 0
        row["vix_dxy"] = row["vix"] * row["dxy_return"]
        row["gpr_vix"] = row["gpr_score"] * row["vix"]

        # 合成标签：利多因子越多越可能上涨
        prob = 0.5
        prob += row["sentiment_score"] * 0.15
        prob += -row["hawkish_score"] * 0.1
        prob += -row["dxy_return"] * 5
        prob += -row["tips_change"] * 0.5
        prob += row["momentum_5m"] * 3
        if row["vix"] > 25:
            prob += 0.04
        prob = max(0.05, min(0.95, prob))
        label = 1 if rng.random() < prob else 0

        data.append(row)
        labels.append(label)

    X = pd.DataFrame(data)[_FEATURES]
    y = pd.Series(labels)
    model = WeightedPredictor()
    model.train(X, y)
    model.save()
    return model
