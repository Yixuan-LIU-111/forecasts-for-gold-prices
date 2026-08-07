"""示例入口 —— 整合 LLM 新闻情感 + 30 分钟行情，完成训练 / 评估 / 消融 / 推理。

用法（从仓库根目录 forecasts for gold prices 执行）：
    # 自动：真实数据足够则训练真实数据，否则回退合成数据演示
    news_scraper_llm/.venv/bin/python3 -m gold_prediction_model.thirty_min.run_pipeline

    # 强制合成数据演示
    ... -m gold_prediction_model.thirty_min.run_pipeline --use-synthetic

    # 仅推理最近一根 30 分钟 bar
    ... -m gold_prediction_model.thirty_min.run_pipeline --predict

对应需求 5：模块解耦、统一配置入口（config）、统一日志（logging_setup）、
附带可运行示例入口。

输出：
- artifacts/ 下模型 joblib + meta
- reports/eval_report_*.json 评估 + 消融报告
- 控制台 + logs/thirty_min.log 完整日志
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

# 允许从仓库根目录以 -m 方式运行
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from . import config
from .logging_setup import get_logger
from . import data_layer as DL
from . import features as F
from . import model as M
from . import evaluate as EV
from . import automl as AM

logger = get_logger("thirty_min.run")


def _section(title: str):
    logger.info("=" * 60)
    logger.info(title)
    logger.info("=" * 60)


def _fit_eval(Xtr, ytr, Xva, yva, Xte, yte, lgb_params=None, xgb_params=None):
    """训练集成模型并在测试集评估，返回 (predictor, metrics)。"""
    pred = M.Predictor().fit(Xtr, ytr, Xva, yva, lgb_params=lgb_params, xgb_params=xgb_params)
    p = pred.predict_proba(Xte)
    m = EV.compute_metrics(yte.to_numpy(), p)
    return pred, m


def run_train(source_override: str | None = None, n_synthetic: int = 2000,
              wf_folds: int = 4, do_tune: bool = True, do_wf: bool = True):
    _section("1) 装配数据（真实锚定 30m K 线 + 真实新闻情感 + 真实 GPR/EPU 压力代理）")
    df, source = DL.build_model_table(use_synthetic_fallback=True, n_synthetic=n_synthetic)
    if source_override:
        source = source_override
    logger.info("数据来源: %s，建模底表 %d 行", source, len(df))
    if df.empty:
        logger.error("无可用数据，终止")
        return None

    _section("2) 特征工程（技术 + 情感聚合 + 市场 + 宏观新闻压力）")
    featured = F.build_features(df)
    X_all, y_all, dates_all, feat_cols = F.make_xy(featured, "all")
    logger.info("训练实际采用特征(%d): %s", len(feat_cols), feat_cols)

    _section("3) 时序划分 70/15/15 + Purge")
    parts = EV.chronological_split(X_all, y_all, dates_all)
    for sp, (Xs, ys, _) in parts.items():
        logger.info("  %-6s n=%d  正类占比=%.3f", sp, len(Xs), ys.mean())
    Xtr, ytr, _ = parts["train"]
    Xva, yva, _ = parts["valid"]
    Xte, yte, _ = parts["test"]

    # ---------------- 4) Purged Walk-Forward CV（无偏泛化估计） ----------------
    wf = None
    if do_wf:
        _section("4) Purged Walk-Forward CV（无偏泛化能力估计）")
        wf = AM.purged_walk_forward_cv(X_all, y_all, dates_all, n_folds=wf_folds)

    # ---------------- 5) AutoML 调参 ----------------
    _section("5) AutoML 分阶段超参搜索（默认参数 → 最优）")
    if do_tune:
        tune = AM.automl_tune(Xtr, ytr, Xva, yva)
        best_joint = tune["best_joint"]
    else:
        tune = {"best_joint": AM.default_joint(), "best_auc": float("nan"),
                "history": [], "n_evals": 0}
        best_joint = tune["best_joint"]
    lgb_params = AM.joint_to_lgb(best_joint)
    xgb_params = AM.joint_to_xgb(best_joint)
    logger.info("调参后联合参数: %s", best_joint)

    # ---------------- 6) 默认参数 vs 调参后（同测试集对照） ----------------
    _section("6) 默认参数 vs 调参后（同测试集对照，量化改进）")
    _, m_def = _fit_eval(Xtr, ytr, Xva, yva, Xte, yte)            # 默认参数
    predictor, m_tuned = _fit_eval(Xtr, ytr, Xva, yva, Xte, yte,
                                   lgb_params=lgb_params, xgb_params=xgb_params)
    predictor.save("primary")
    delta_auc = m_tuned["auc"] - m_def["auc"]
    delta_acc = m_tuned["accuracy"] - m_def["accuracy"]
    logger.info("  默认 AUC=%.4f Acc=%.4f | 调参后 AUC=%.4f Acc=%.4f | ΔAUC=%.4f",
                m_def["auc"], m_def["accuracy"], m_tuned["auc"], m_tuned["accuracy"], delta_auc)
    base = EV.baseline_metrics(ytr.to_numpy(), yte.to_numpy())
    logger.info("  基线 majority=%.4f / always_up=%.4f / prior AUC=%.4f",
                base["majority"]["auc"], base["always_up"]["auc"], base["prior"]["auc"])

    # ---------------- 7) 情感特征消融 ----------------
    _section("7) 情感特征消融（含 vs 不含情感）")
    ablation = EV.run_ablation(featured)
    logger.info("  ΔAUC=%.4f  ΔAcc=%.4f", ablation["delta_auc"], ablation["delta_accuracy"])
    logger.info("  结论: %s", ablation["conclusion"])

    # ---------------- 8) 最新 30 分钟 bar 推理 ----------------
    _section("8) 最新 30 分钟 bar 推理")
    last_row = featured.dropna(subset=feat_cols).iloc[[-1]]
    pred = predictor.predict_direction(last_row)
    logger.info("  %s  上涨概率=%.4f  置信度=%.4f  多空分=%s",
                pred["direction"], pred["probability"], pred["confidence"], pred["bull_bear_score"])

    # ---------------- 报告落盘 ----------------
    report = {
        "source": source,
        "n_samples": int(len(featured)),
        "feature_cols": feat_cols,
        "walk_forward": {k: v for k, v in (wf or {}).items() if k != "folds"},
        "automl": {"best_joint": best_joint, "best_val_auc": tune["best_auc"],
                   "n_evals": tune["n_evals"]},
        "test_default_params": m_def,
        "test_tuned_params": m_tuned,
        "improvement": {"delta_auc": delta_auc, "delta_accuracy": delta_acc},
        "with_sentiment_metrics": ablation["with_sentiment"],
        "without_sentiment_metrics": ablation["without_sentiment"],
        "baseline": {k: v for k, v in base.items() if not k.startswith("_")},
        "ablation_delta": {"auc": ablation["delta_auc"], "accuracy": ablation["delta_accuracy"]},
        "ablation_conclusion": ablation["conclusion"],
        "latest_prediction": pred,
        "horizon_minutes": config.HORIZON_MINUTES,
        "predict_window": config.PREDICT_WINDOW,
    }
    rp = config.REPORT_DIR / f"eval_report_{pd.Timestamp.now():%Y%m%d_%H%M%S}.json"
    with open(rp, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2, default=str)
    logger.info("评估报告已保存: %s", rp)
    return report


def run_predict():
    _section("推理模式：预测最新 30 分钟窗口方向")
    try:
        predictor = M.Predictor.load("primary")
    except Exception as e:
        logger.warning("未找到已训练模型(%s)，改为训练后推理", e)
        run_train()
        predictor = M.Predictor.load("primary")
    df, source = DL.build_model_table(use_synthetic_fallback=False)
    if df.empty:
        df, source = DL.build_model_table(use_synthetic_fallback=True)
    featured = F.build_features(df)
    feat_cols = F.available_features(featured, "all")
    last_row = featured.dropna(subset=feat_cols).iloc[[-1]]
    pred = predictor.predict_direction(last_row)
    logger.info("数据来源: %s", source)
    logger.info("最新预测: %s | 上涨概率=%.4f | 置信度=%.4f | 多空分=%s",
                pred["direction"], pred["probability"], pred["confidence"], pred["bull_bear_score"])
    print(json.dumps(pred, ensure_ascii=False, indent=2))
    return pred


def main():
    ap = argparse.ArgumentParser(description="黄金 30 分钟预测：LLM 情感 + 量化集成 + AutoML")
    ap.add_argument("--use-synthetic", action="store_true", help="强制使用合成数据演示")
    ap.add_argument("--n-synthetic", type=int, default=2000, help="合成 bar 数量")
    ap.add_argument("--predict", action="store_true", help="仅推理最新 30 分钟 bar")
    ap.add_argument("--no-tune", action="store_true", help="跳过 AutoML 调参（用默认参数）")
    ap.add_argument("--no-wf", action="store_true", help="跳过 Walk-Forward CV（加速）")
    ap.add_argument("--wf-folds", type=int, default=4, help="Walk-Forward 折数")
    args = ap.parse_args()

    if args.predict:
        run_predict()
        return
    run_train(source_override="synthetic" if args.use_synthetic else None,
              n_synthetic=args.n_synthetic, wf_folds=args.wf_folds,
              do_tune=not args.no_tune, do_wf=not args.no_wf)


if __name__ == "__main__":
    main()
