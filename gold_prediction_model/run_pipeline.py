"""一键可复现管道：数据 → 特征 → 训练 → 评估 → 报告。

用法：
    python run_pipeline.py                # 用缓存数据跑全流程
    python run_pipeline.py --refresh      # 强制重新抓取黄金价格
    python run_pipeline.py --no-ablation  # 跳过消融实验（更快）
"""

from __future__ import annotations

import argparse
import json
import platform
import sys
from datetime import datetime

import numpy as np
import pandas as pd

import config as C
import data_loader
import evaluate as E
import features as F
import train as T


def _fmt(df: pd.DataFrame, floatfmt: str = "%.4f") -> str:
    return df.to_string(index=False, float_format=lambda v: floatfmt % v)


def run(refresh: bool = False, ablation: bool = True) -> dict:
    log: list[str] = []

    def emit(s: str = ""):
        print(s)
        log.append(s)

    emit("=" * 78)
    emit("「点时成金」黄金价格方向预测模型 —— 训练与评估管道")
    emit("=" * 78)
    emit(f"运行时间: {datetime.now():%Y-%m-%d %H:%M:%S}")
    emit(f"Python  : {platform.python_version()}  |  平台: {platform.platform()}")
    emit(f"随机种子: {C.RANDOM_SEED}")
    emit()

    # ---------------------------------------------------------- 1. 数据
    emit("─" * 78)
    emit("【1】数据加载与对齐")
    emit("─" * 78)
    base = data_loader.build_dataset(refresh=refresh)
    emit(f"黄金日线(COMEX GC) + 宏观指标 对齐完成")
    emit(f"  区间: {base['date'].min().date()} ~ {base['date'].max().date()}")
    emit(f"  行数: {len(base)}   字段: {len(base.columns)}")
    emit(f"  缺失: {int(base.isna().sum().sum())}")
    emit()

    # ---------------------------------------------------------- 2. 特征
    emit("─" * 78)
    emit("【2】特征工程（对齐方案文档 §9.4）")
    emit("─" * 78)
    feat = F.build_features(base)
    feat.to_csv(C.FEATURES_CSV, index=False)

    X, y, dates, cols = F.make_xy(feat, C.PRIMARY_FEATURE_SET)
    parts = F.chronological_split(X, y, dates)

    emit(f"预测跨度 horizon = {C.HORIZON} bar（日频 → {C.HORIZON} 个交易日）")
    emit(f"滚动窗口 window  = {C.ROLL_WINDOW} bar")
    emit(f"特征 ({len(cols)}): {cols}")
    if not any(c in feat.columns for c in C.FEATURES_SENTIMENT_OPTIONAL):
        emit("提示: 情感/鹰鸽特征在历史样本中不存在，管道已自动跳过（保留接入位）")
    emit(f"有效样本: {len(X)}   正类占比: {y.mean():.4f}")
    emit()
    emit("时间顺序划分（文档 §9.5 = 70/15/15）:")
    for nm, (Xs, ys, ds) in parts.items():
        emit(f"  {nm:6s} n={len(Xs):5d}  {ds.min().date()} ~ {ds.max().date()}  "
             f"正类占比={ys.mean():.4f}")
    emit()

    # ---------------------------------------------------------- 3. 训练
    emit("─" * 78)
    emit("【3】双模型训练（LightGBM 基线 + XGBoost 对比）")
    emit("─" * 78)
    models, proba = T.fit_dual_models(parts)
    emit(f"LightGBM  best_iteration = {models['lgb'].best_iteration_}")
    emit(f"XGBoost   best_iteration = {models['xgb'].best_iteration}")
    emit(f"融合权重  p = {C.ENSEMBLE_W_LGB}*p_lgb + {C.ENSEMBLE_W_XGB}*p_xgb")
    paths = T.save_models(models, cols, tag="primary")
    emit(f"模型已序列化: {list(paths.values())}")
    emit()

    # ---------------------------------------------------------- 4. 评估
    emit("─" * 78)
    emit("【4】性能评估（准确率 / F1 / AUC / LogLoss）")
    emit("─" * 78)
    mdf = E.evaluate_all_splits(proba)
    emit(_fmt(mdf))
    emit()

    y_tr = parts["train"][1]
    y_te = parts["test"][1]
    bl = E.baseline_metrics(y_tr, y_te)
    bl_rows = pd.DataFrame([
        {"基线": "多数类(恒定预测训练集多数类)", **{k: bl["majority"][k]
         for k in ("accuracy", "f1", "auc", "logloss")}},
        {"基线": "恒定看涨(≈买入持有)", **{k: bl["always_up"][k]
         for k in ("accuracy", "f1", "auc", "logloss")}},
        {"基线": "训练集先验概率", **{k: bl["prior"][k]
         for k in ("accuracy", "f1", "auc", "logloss")}},
    ])
    emit("基线对照（测试集）:")
    emit(_fmt(bl_rows))
    emit()

    test_acc = mdf.query("split=='test' and model=='ensemble'")["accuracy"].iloc[0]
    base_acc = bl["always_up"]["accuracy"]
    emit(f"融合模型测试集准确率 = {test_acc:.4f}")
    emit(f"最强朴素基线准确率   = {max(bl['majority']['accuracy'], base_acc):.4f}")
    emit(f"超额 = {test_acc - max(bl['majority']['accuracy'], base_acc):+.4f}")
    emit()

    emit("过拟合检测（文档 §9.5 阈值 15%）:")
    of = E.overfit_check(mdf)
    for m, d in of.items():
        flag = "⚠ 告警" if d["alert"] else "✓ 正常"
        emit(f"  {m:9s} train={d['train_acc']:.4f} test={d['test_acc']:.4f} "
             f"gap={d['gap']:+.4f}  {flag}")
    emit()

    emit("混淆矩阵（测试集 · 融合模型 · 阈值 0.5）:")
    emit(E.confusion(proba["test"]["y"], proba["test"]["ensemble"]).to_string())
    emit()

    emit("按文档 §10.1 信号规则的实际发单准确率（测试集）:")
    emit(_fmt(E.signal_rule_evaluation(proba["test"]["y"], proba["test"]["ensemble"])))
    emit()

    # ---------------------------------------------------------- 5. Walk-Forward
    emit("─" * 78)
    emit("【5】Walk-Forward 滚动验证（文档 §9.5，防特征泄露）")
    emit("─" * 78)
    wf = T.walk_forward(X, y, dates)
    if len(wf):
        show = wf[["fold", "test_start", "test_end", "n_test",
                   "accuracy", "f1", "auc", "logloss"]]
        emit(show.to_string(index=False, float_format=lambda v: "%.4f" % v))
        emit()
        emit(f"各折平均: accuracy={wf['accuracy'].mean():.4f} "
             f"(±{wf['accuracy'].std():.4f})  auc={wf['auc'].mean():.4f}  "
             f"logloss={wf['logloss'].mean():.4f}")
    else:
        emit("样本量不足，未产生有效折。")
    emit()

    # ---------------------------------------------------------- 6. 重要性
    emit("─" * 78)
    emit("【6】特征重要性归因（文档 §10.5）")
    emit("─" * 78)
    imp = T.feature_importance(models, cols)
    emit(_fmt(imp[["feature", "lgb_gain_pct", "xgb_gain_pct"]], "%.2f"))
    emit()

    # ---------------------------------------------------------- 7. 消融
    abl_df = None
    if ablation:
        emit("─" * 78)
        emit("【7】消融对比：GPR / EPU 的边际贡献")
        emit("─" * 78)
        rows = []
        for fs in ("p0_doc", "full"):
            Xa, ya, da, ca = F.make_xy(feat, fs)
            pa = F.chronological_split(Xa, ya, da)
            _, pra = T.fit_dual_models(pa)
            m = E.compute_metrics(pra["test"]["y"], pra["test"]["ensemble"])
            rows.append({
                "特征集": "仅文档P0(价格+DXY/TIPS/VIX)" if fs == "p0_doc"
                          else "全特征(+GPR/EPU)",
                "特征数": len(ca), **{k: m[k] for k in
                ("accuracy", "f1", "auc", "logloss")},
            })
        abl_df = pd.DataFrame(rows)
        emit(_fmt(abl_df))
        d_acc = abl_df["accuracy"].iloc[1] - abl_df["accuracy"].iloc[0]
        d_auc = abl_df["auc"].iloc[1] - abl_df["auc"].iloc[0]
        emit()
        emit(f"GPR/EPU 边际贡献: Δaccuracy = {d_acc:+.4f}   Δauc = {d_auc:+.4f}")
        emit()

    # ---------------------------------------------------------- 8. 多跨度
    emit("─" * 78)
    emit("【8】多跨度稳健性对照（辅助参考）")
    emit("─" * 78)
    hz_rows = []
    for h, tc in [(C.HORIZON, "target")] + [(h, f"target_h{h}") for h in C.AUX_HORIZONS]:
        Xh, yh, dh, ch = F.make_xy(feat, C.PRIMARY_FEATURE_SET, target_col=tc)
        ph = F.chronological_split(Xh, yh, dh)
        _, prh = T.fit_dual_models(ph)
        m = E.compute_metrics(prh["test"]["y"], prh["test"]["ensemble"])
        b = E.baseline_metrics(ph["train"][1], ph["test"][1])
        naive = max(b["majority"]["accuracy"], b["always_up"]["accuracy"])
        hz_rows.append({
            "预测跨度": f"T+{h} 交易日" + ("  ← 主模型" if tc == "target" else ""),
            "测试集n": len(prh["test"]["y"]),
            "accuracy": m["accuracy"], "auc": m["auc"], "logloss": m["logloss"],
            "朴素基线": naive, "超额": m["accuracy"] - naive,
        })
    hz_df = pd.DataFrame(hz_rows)
    emit(_fmt(hz_df))
    emit()

    # ---------------------------------------------------------- 汇总落盘
    summary = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "data": {
            "range": [str(base["date"].min().date()), str(base["date"].max().date())],
            "rows": int(len(base)),
            "effective_samples": int(len(X)),
            "positive_rate": float(y.mean()),
        },
        "config": {
            "horizon_bars": C.HORIZON,
            "roll_window": C.ROLL_WINDOW,
            "split": [C.TRAIN_RATIO, C.VALID_RATIO, C.TEST_RATIO],
            "ensemble_weights": [C.ENSEMBLE_W_LGB, C.ENSEMBLE_W_XGB],
            "features": cols,
        },
        "metrics": mdf.to_dict(orient="records"),
        "baselines": {k: v for k, v in bl.items() if not k.startswith("_")},
        "baseline_context": {k: v for k, v in bl.items() if k.startswith("_")},
        "overfit_check": of,
        "walk_forward": wf.to_dict(orient="records") if len(wf) else [],
        "feature_importance": imp.to_dict(orient="records"),
        "ablation": abl_df.to_dict(orient="records") if abl_df is not None else [],
        "horizon_comparison": hz_df.to_dict(orient="records"),
    }
    out_json = C.REPORT_DIR / "metrics.json"
    out_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2,
                                   default=str), encoding="utf-8")
    (C.REPORT_DIR / "run_log.txt").write_text("\n".join(log), encoding="utf-8")

    emit("=" * 78)
    emit(f"完成。指标: {out_json}")
    emit(f"      日志: {C.REPORT_DIR / 'run_log.txt'}")
    emit("=" * 78)
    return summary


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true", help="强制重新抓取黄金价格")
    ap.add_argument("--no-ablation", action="store_true", help="跳过消融实验")
    a = ap.parse_args()
    run(refresh=a.refresh, ablation=not a.no_ablation)
