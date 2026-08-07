"""模型定义模块 —— 黄金方向预测模型（LightGBM + XGBoost 集成）。

封装「训练 / 推理」逻辑，对上层（pipeline）提供干净的接口：
  - fit(feats)         : 在开发集上用 purged walk-forward CV 选定树数，
                          隔离测试集评估一次；并用全量数据重训「生产模型」供推理
  - predict(X)         : 输出上涨概率 / 类别 / 方向
  - evaluate(X, y)     : 输出 accuracy/F1/AUC/LogLoss + 朴素基线对照
  - save/load          : joblib 序列化（特征清单 + 双模型 + 超参）
  - tune(feats)        : AutoML 式调参（优先级：特征集→lr→复杂度→采样→L1/L2）

防泄露约束（与 select_model 一致）：
  - 开发集=前85%，测试集=后15%（purge 边界），测试集仅评估一次
  - 超参选择只在开发集内部完成
"""
from __future__ import annotations

import joblib
import logging
from pathlib import Path

import numpy as np
import pandas as pd

import config as C
import evaluate as E
import features as F
import select_model as SM
import train as T

log = logging.getLogger("model")

DEVT_RATIO = C.TRAIN_RATIO + C.VALID_RATIO  # 0.85


class GoldDirectionModel:
    """黄金价格方向预测模型（二分类：未来 HORIZON 根 bar 后是否上涨）。"""

    def __init__(self, feature_set: str = C.PRIMARY_FEATURE_SET,
                 lgb_params: dict | None = None, xgb_params: dict | None = None,
                 target_col: str = "target", tag: str = "primary"):
        self.feature_set = feature_set
        self.lgb_params = dict(C.LGB_PARAMS if lgb_params is None else lgb_params)
        self.xgb_params = dict(C.XGB_PARAMS if xgb_params is None else xgb_params)
        self.target_col = target_col
        self.tag = tag

        self.feature_cols: list[str] | None = None
        self.dev_models: dict | None = None
        self.models: dict | None = None          # 生产模型（全量重训）
        self.n_estimators: int | None = None
        self.cv_auc: float | None = None
        self.test_metrics: dict | None = None
        self.naive_acc: float | None = None
        self.importance: pd.DataFrame | None = None
        self.is_fitted = False
        # 预测目标时间语义（方案文档：未来 30 分钟方向）
        self.horizon_minutes = C.TARGET_HORIZON_MINUTES
        self.target_description = C.PREDICTION_TARGET

    # -------------------------------------------------------------- 训练
    def fit(self, feats: pd.DataFrame, dev_ratio: float = DEVT_RATIO,
            purged: bool = True) -> "GoldDirectionModel":
        X, y, d, cols = F.make_xy(feats, self.feature_set, self.target_col)
        self.feature_cols = cols

        (Xd, yd, dd), (Xt, yt, dt) = SM.dev_test_split(
            X, y, d, purge=C.PURGE_BARS if purged else 0)

        # 1) 开发集 purged CV 选定树数（测试集不参与）
        ne, cv_auc = T.purged_cv_score(Xd, yd, self.lgb_params, self.xgb_params)
        self.n_estimators, self.cv_auc = int(ne), float(cv_auc)
        log.info("CV 选定 n_estimators=%d (CV_AUC=%.4f)", ne, cv_auc)

        # 2) 开发集拟合（用于评估）+ 全量重训生产模型（用于推理）
        self.dev_models = T.fit_fixed(Xd, yd, self.lgb_params, self.xgb_params, ne, ne)
        self.models = T.fit_fixed(X, y, self.lgb_params, self.xgb_params, ne, ne)

        # 3) 隔离测试集评估一次
        pe = self._proba(self.dev_models, Xt)
        self.test_metrics = E.compute_metrics(yt.to_numpy(), pe)
        bl = E.baseline_metrics(yd, yt)
        self.naive_acc = max(bl["majority"]["accuracy"], bl["always_up"]["accuracy"])

        self.importance = T.feature_importance(self.dev_models, cols)
        self.is_fitted = True
        log.info("测试集: accuracy=%.4f (基线 %.4f, 超额 %+.4f) AUC=%.4f",
                 self.test_metrics["accuracy"], self.naive_acc,
                 self.test_metrics["accuracy"] - self.naive_acc, self.test_metrics["auc"])
        return self

    # -------------------------------------------------------------- 推理
    def _proba(self, models: dict, X: pd.DataFrame) -> np.ndarray:
        p_l = models["lgb"].predict_proba(X[self.feature_cols].astype(float))[:, 1]
        p_x = models["xgb"].predict_proba(X[self.feature_cols].astype(float))[:, 1]
        return T.ensemble_proba(p_l, p_x)

    def predict(self, X: pd.DataFrame, return_proba: bool = True) -> pd.DataFrame:
        if not self.is_fitted:
            raise RuntimeError("模型尚未训练，请先调用 fit() 或 load()")
        p = self._proba(self.models, X)
        out = pd.DataFrame({"proba_up": p, "pred_class": (p >= 0.5).astype(int)})
        out["direction"] = np.where(out["pred_class"] == 1, "涨", "跌")
        out["horizon_minutes"] = self.horizon_minutes
        return out if return_proba else out[["pred_class", "direction"]]

    def evaluate(self, X: pd.DataFrame, y) -> dict:
        p = self._proba(self.models, X)
        return E.compute_metrics(np.asarray(y).astype(int), p)

    # -------------------------------------------------------------- 持久化
    def save(self, out_dir: Path = C.ARTIFACT_DIR) -> dict:
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        paths = T.save_models(self.models, self.feature_cols, tag=self.tag)
        meta = {
            "feature_set": self.feature_set,
            "target_col": self.target_col,
            "target_description": self.target_description,
            "horizon_minutes": self.horizon_minutes,
            "n_estimators": self.n_estimators,
            "cv_auc": self.cv_auc,
            "lgb_params": self.lgb_params,
            "xgb_params": self.xgb_params,
            "feature_cols": self.feature_cols,
            "test_metrics": self.test_metrics,
            "naive_acc": self.naive_acc,
            "ensemble_weights": {"lgb": C.ENSEMBLE_W_LGB, "xgb": C.ENSEMBLE_W_XGB},
        }
        joblib.dump(meta, out_dir / f"{self.tag}_meta.joblib")
        return paths

    @classmethod
    def load(cls, tag: str = "primary",
             out_dir: Path = C.ARTIFACT_DIR) -> "GoldDirectionModel":
        out_dir = Path(out_dir)
        meta = joblib.load(out_dir / f"{tag}_meta.joblib")
        obj = cls(feature_set=meta["feature_set"], target_col=meta["target_col"], tag=tag)
        obj.lgb_params, obj.xgb_params = meta["lgb_params"], meta["xgb_params"]
        obj.n_estimators = meta["n_estimators"]
        obj.cv_auc = meta["cv_auc"]
        obj.feature_cols = meta["feature_cols"]
        obj.test_metrics = meta.get("test_metrics")
        obj.naive_acc = meta.get("naive_acc")
        obj.target_description = meta.get("target_description", C.PREDICTION_TARGET)
        obj.horizon_minutes = meta.get("horizon_minutes", C.TARGET_HORIZON_MINUTES)
        obj.models = {
            "lgb": joblib.load(out_dir / f"{tag}_lgb.joblib"),
            "xgb": joblib.load(out_dir / f"{tag}_xgb.joblib"),
        }
        obj.is_fitted = True
        return obj

    # -------------------------------------------------------------- AutoML 调参
    def tune(self, feats: pd.DataFrame, dev_ratio: float = DEVT_RATIO,
             feature_sets=("p0_doc", "full", "p0_stat", "full_stat")) -> dict:
        """AutoML 式调参（优先级：特征集 → lr → 复杂度 → 采样 → L1/L2）。

        全程只在开发集 purged CV 上选参；返回最优配置字典并更新自身。
        """
        X, y, d, _ = F.make_xy(feats, self.feature_set, self.target_col)
        (Xd, yd, dd), _ = SM.dev_test_split(X, y, d)

        def cv(params_lgb, params_xgb):
            return T.purged_cv_score(Xd, yd, params_lgb, params_xgb)

        # 阶段1：特征集
        _ = cv  # 复用闭包以统一调用入口
        best_fs, best_auc = self.feature_set, -1
        for fs in feature_sets:
            Xf, yf, df_, _ = F.make_xy(feats, fs, self.target_col)
            (Xdf, ydf, ddf), _ = SM.dev_test_split(Xf, yf, df_)
            ne, a = T.purged_cv_score(Xdf, ydf, self.lgb_params, self.xgb_params)
            log.info("  [tune] featset=%-10s CV_AUC=%.4f", fs, a)
            if a > best_auc:
                best_auc, best_fs = a, fs
        self.feature_set = best_fs

        # 阶段2：learning_rate
        best_lr, best_auc = self.lgb_params["learning_rate"], best_auc
        for lr in (0.01, 0.02, 0.05, 0.1):
            lp = dict(self.lgb_params, learning_rate=lr)
            xp = dict(self.xgb_params, learning_rate=lr)
            ne, a = T.purged_cv_score(Xd, yd, lp, xp)
            log.info("  [tune] lr=%.3f CV_AUC=%.4f", lr, a)
            if a > best_auc:
                best_auc, best_lr = a, lr
        self.lgb_params["learning_rate"] = best_lr
        self.xgb_params["learning_rate"] = best_lr

        # 阶段3：复杂度
        best_cx, best_auc = (self.lgb_params["num_leaves"], self.xgb_params["max_depth"]), best_auc
        for nl, md in [(7, 3), (15, 4), (31, 6)]:
            lp = dict(self.lgb_params, num_leaves=nl, min_child_samples=40)
            xp = dict(self.xgb_params, max_depth=md, min_child_weight=10)
            ne, a = T.purged_cv_score(Xd, yd, lp, xp)
            log.info("  [tune] leaves=%d depth=%d CV_AUC=%.4f", nl, md, a)
            if a > best_auc:
                best_auc, best_cx = a, (nl, md)
        self.lgb_params.update(num_leaves=best_cx[0], min_child_samples=40)
        self.xgb_params.update(max_depth=best_cx[1], min_child_weight=10)

        # 阶段4：采样正则
        best_sp, best_auc = (1.0, 1.0), best_auc
        for ss, cs in [(1.0, 1.0), (0.9, 0.9), (0.8, 0.7)]:
            lp = dict(self.lgb_params, subsample=ss, subsample_freq=1, colsample_bytree=cs)
            xp = dict(self.xgb_params, subsample=ss, colsample_bytree=cs)
            ne, a = T.purged_cv_score(Xd, yd, lp, xp)
            log.info("  [tune] sub=%.1f col=%.1f CV_AUC=%.4f", ss, cs, a)
            if a > best_auc:
                best_auc, best_sp = a, (ss, cs)
        self.lgb_params.update(subsample=best_sp[0], subsample_freq=1, colsample_bytree=best_sp[1])
        self.xgb_params.update(subsample=best_sp[0], colsample_bytree=best_sp[1])

        # 阶段5：L1/L2
        best_rg, best_auc = (self.lgb_params["reg_alpha"], self.lgb_params["reg_lambda"]), best_auc
        for a, l in [(0.1, 1.0), (1.0, 10.0)]:
            lp = dict(self.lgb_params, reg_alpha=a, reg_lambda=l)
            xp = dict(self.xgb_params, reg_alpha=a, reg_lambda=l)
            ne, a_ = T.purged_cv_score(Xd, yd, lp, xp)
            log.info("  [tune] alpha=%.1f lambda=%.1f CV_AUC=%.4f", a, l, a_)
            if a_ > best_auc:
                best_auc, best_rg = a_, (a, l)
        self.lgb_params.update(reg_alpha=best_rg[0], reg_lambda=best_rg[1])
        self.xgb_params.update(reg_alpha=best_rg[0], reg_lambda=best_rg[1])

        cfg = {"feature_set": self.feature_set, "lgb_params": self.lgb_params,
               "xgb_params": self.xgb_params, "cv_auc": best_auc}
        log.info("调参完成: %s", cfg)
        return cfg


if __name__ == "__main__":
    import collector as CL
    import preprocess as PP

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    g, m = CL.MarketCollector().collect_all()
    feats = PP.run(g, m, save=True)

    model = GoldDirectionModel(feature_set="full_stat")
    model.fit(feats)
    print("测试指标:", model.test_metrics)
    preds = model.predict(feats.iloc[-5:])
    print(preds)
