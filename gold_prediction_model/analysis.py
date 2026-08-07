"""清洁版消融 + 稳健性分析（与 select_model 同一套无泄露方法论）。

产出：
  reports/ablation_clean.tsv / .json    —— GPR/EPU 边际贡献（开发集CV + 隔离测试集）
  reports/walkforward_clean.tsv         —— 清洁版 Walk-Forward（T+30 主目标）
  reports/figures/*.png                 —— 报告用图
  reports/analysis_summary.json         —— 报告汇总数字

方法论约束（与 select_model.py 一致，测试集全程隔离）：
  - 开发集 = 前 85%（train+valid），测试集 = 后 15%
  - 超参固定为文档默认（num_leaves=31 / max_depth=6 / lr=0.05），
    仅通过开发集 purged walk-forward CV 选择树数，从而隔离「特征」这一变量
  - 测试集仅评估一次
"""
from __future__ import annotations

import json
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

import config as C
import data_loader
import features as F
import train as T
import evaluate as E
import select_model as SM

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

warnings.filterwarnings("ignore")

PY = "/Users/echo/.workbuddy/binaries/python/envs/default/bin/python"
FIG = C.REPORT_DIR / "figures"
FIG.mkdir(parents=True, exist_ok=True)

# ------------------------------------------------------------------ 数据
base = data_loader.build_dataset(save=False)
feat = F.build_features(base)

HORIZONS = [("target", "T+30"), ("target_h5", "T+5"), ("target_h1", "T+1")]

# ------------------------------------------------------------------ 消融变体
# 基底 = 平稳化后的价格 + 市场特征（文档 P0 范围），再逐步加入政策风险指标
BASE = C.FEATURES_PRICE_STAT + C.FEATURES_MARKET_STAT
RISK = C.FEATURES_RISK_STAT  # [gpr_z, gpr_change_pct, epu_z, epu_change_pct]
VARIANTS = {
    "P0_无政策风险": BASE,
    "P0+GPR": BASE + RISK[:2],
    "P0+EPU": BASE + RISK[2:],
    "P0+GPR+EPU_全": BASE + RISK,
}

lgb_p = dict(C.LGB_PARAMS)
xgb_p = dict(C.XGB_PARAMS)


def make_xy_custom(df, feats, target_col):
    sub = df[["date"] + feats + [target_col]].copy().dropna().reset_index(drop=True)
    return sub[feats].astype(float), sub[target_col].astype(int), sub["date"]


def clean_walk_forward(X, y, d, n_splits=5, lgb_p=lgb_p, xgb_p=xgb_p):
    """清洁版 Walk-Forward：扩张窗口 + 每折 purged CV 选树数，训练永远早于测试。"""
    n = len(X)
    fold = n // (n_splits + 1)
    rows = []
    for k in range(1, n_splits + 1):
        end_tr = fold * k
        end_te = fold * (k + 1) if k < n_splits else n
        tr_end = max(0, end_tr - C.PURGE_BARS)
        if tr_end < 100 or end_te - end_tr < 20:
            continue
        if y.iloc[end_tr:end_te].nunique() < 2:
            continue
        Xtr, ytr = X.iloc[:tr_end], y.iloc[:tr_end]
        Xte, yte = X.iloc[end_tr:end_te], y.iloc[end_tr:end_te]
        ne, _ = T.purged_cv_score(Xtr, ytr, lgb_p, xgb_p)
        ms = T.fit_fixed(Xtr, ytr, lgb_p, xgb_p, ne, ne)
        pe = T.ensemble_proba(ms["lgb"].predict_proba(Xte)[:, 1],
                              ms["xgb"].predict_proba(Xte)[:, 1])
        m = E.compute_metrics(yte.to_numpy(), pe)
        m.update({"fold": k,
                  "test_start": d.iloc[end_tr].date(),
                  "test_end": d.iloc[end_te - 1].date(),
                  "n_test": len(yte)})
        rows.append(m)
    return pd.DataFrame(rows)


# ------------------------------------------------------------------ 消融主循环
print("=" * 78)
print("清洁版消融：GPR / EPU 边际贡献（测试集隔离）")
print("=" * 78)

abl_rows = []
for tc, lbl in HORIZONS:
    for vname, vfeats in VARIANTS.items():
        X, y, d = make_xy_custom(feat, vfeats, tc)
        (Xd, yd, dd), (Xt, yt, dt) = SM.dev_test_split(X, y, d)
        if len(Xt) < 20:
            continue
        ne, cv_auc = T.purged_cv_score(Xd, yd, lgb_p, xgb_p)
        models = T.fit_fixed(Xd, yd, lgb_p, xgb_p, ne, ne)
        pe = T.ensemble_proba(models["lgb"].predict_proba(Xt)[:, 1],
                              models["xgb"].predict_proba(Xt)[:, 1])
        m = E.compute_metrics(yt.to_numpy(), pe)
        bl = E.baseline_metrics(yd, yt)
        naive = max(bl["majority"]["accuracy"], bl["always_up"]["accuracy"])
        abl_rows.append({
            "horizon": lbl,
            "variant": vname,
            "n_features": len(vfeats),
            "cv_auc": round(cv_auc, 4),
            "best_n_estimators": ne,
            "test_accuracy": round(m["accuracy"], 4),
            "test_auc": round(m["auc"], 4),
            "test_f1": round(m["f1"], 4),
            "test_logloss": round(m["logloss"], 4),
            "naive_accuracy": round(naive, 4),
            "excess_accuracy": round(m["accuracy"] - naive, 4),
        })
        print(f"  {lbl:5s} {vname:16s} n={len(vfeats)} "
              f"CV_AUC={cv_auc:.4f}  test_acc={m['accuracy']:.4f} "
              f"(naive {naive:.4f}, excess {m['accuracy']-naive:+.4f}) "
              f"AUC={m['auc']:.4f}")

abl_df = pd.DataFrame(abl_rows)
abl_df.to_csv(C.REPORT_DIR / "ablation_clean.tsv", sep="\t", index=False)
abl_df.to_json(C.REPORT_DIR / "ablation_clean.json", force_ascii=False, indent=2)

# ------------------------------------------------------------------ 特征重要性（全模型 T+30）
print("\n" + "=" * 78)
print("特征重要性归因（平稳化全特征，T+30）")
print("=" * 78)
X, y, d, cols = F.make_xy(feat, "full_stat", target_col="target")
(Xd, yd, dd), _ = SM.dev_test_split(X, y, d)
ne, _ = T.purged_cv_score(Xd, yd, lgb_p, xgb_p)
models = T.fit_fixed(Xd, yd, lgb_p, xgb_p, ne, ne)
T.save_models(models, cols, tag="primary_clean")
imp = T.feature_importance(models, cols)
print(imp.to_string(index=False))

# ------------------------------------------------------------------ 清洁 Walk-Forward (T+30)
print("\n" + "=" * 78)
print("清洁版 Walk-Forward（T+30，平稳化全特征）")
print("=" * 78)
wf = clean_walk_forward(X, y, d, n_splits=5)
wf.to_csv(C.REPORT_DIR / "walkforward_clean.tsv", sep="\t", index=False)
print(wf[["fold", "test_start", "test_end", "n_test",
          "accuracy", "auc", "logloss"]].to_string(index=False))
print(f"\n各折平均: accuracy={wf['accuracy'].mean():.4f} (±{wf['accuracy'].std():.4f})  "
      f"auc={wf['auc'].mean():.4f}  logloss={wf['logloss'].mean():.4f}")

# ------------------------------------------------------------------ 汇总 JSON（给报告用）
selected = json.loads((C.REPORT_DIR / "selected_configs.json").read_text(encoding="utf-8"))
summary = {
    "data": {
        "range": [str(base["date"].min().date()), str(base["date"].max().date())],
        "rows": int(len(base)),
        "effective_samples": int(len(X)),
        "positive_rate": round(float(y.mean()), 4),
    },
    "selected_configs": selected,
    "ablation": abl_rows,
    "walk_forward": {
        "folds": wf.to_dict(orient="records"),
        "mean_accuracy": round(float(wf["accuracy"].mean()), 4),
        "std_accuracy": round(float(wf["accuracy"].std()), 4),
        "mean_auc": round(float(wf["auc"].mean()), 4),
        "mean_logloss": round(float(wf["logloss"].mean()), 4),
    },
    "feature_importance": imp.to_dict(orient="records"),
}
(C.REPORT_DIR / "analysis_summary.json").write_text(
    json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

# =================================================================== 绘图
plt.rcParams.update({"figure.dpi": 130, "font.size": 10,
                     "axes.grid": True, "grid.alpha": 0.3})

# 图1：各跨度 测试准确率 vs 朴素基线
fig, ax = plt.subplots(figsize=(6.2, 3.6))
hs = [h for _, h in HORIZONS]
acc = [selected[h]["test_metrics"]["accuracy"] for h in hs]
naive = [selected[h]["naive_acc"] for h in hs]
x = np.arange(len(hs)); w = 0.38
ax.bar(x - w/2, acc, w, label="集成模型", color="#c0392b")
ax.bar(x + w/2, naive, w, label="朴素基线(多数类)", color="#7f8c8d")
for i, (a, n) in enumerate(zip(acc, naive)):
    ax.text(i - w/2, a + 0.01, f"{a:.3f}", ha="center", fontsize=8)
    ax.text(i + w/2, n + 0.01, f"{n:.3f}", ha="center", fontsize=8)
ax.set_xticks(x); ax.set_xticklabels(hs)
ax.set_ylim(0.4, 0.75); ax.set_ylabel("Accuracy")
ax.set_title("Test Accuracy: Ensemble vs Naive Baseline (T+1/5/30)")
ax.legend(fontsize=8)
fig.tight_layout(); fig.savefig(FIG / "fig_accuracy.png"); plt.close(fig)

# 图2：各跨度 测试 AUC vs 0.5
fig, ax = plt.subplots(figsize=(6.2, 3.6))
auc = [selected[h]["test_metrics"]["auc"] for h in hs]
ax.bar(x, auc, w*1.4, color="#2980b9")
ax.axhline(0.5, color="#e67e22", ls="--", lw=1.2, label="random (0.5)")
for i, a in enumerate(auc):
    ax.text(i, a + 0.005, f"{a:.3f}", ha="center", fontsize=8)
ax.set_xticks(x); ax.set_xticklabels(hs)
ax.set_ylim(0.4, 0.65); ax.set_ylabel("AUC")
ax.set_title("Test AUC by Horizon (closer to 0.5 = no signal)")
ax.legend(fontsize=8)
fig.tight_layout(); fig.savefig(FIG / "fig_auc.png"); plt.close(fig)

# 图3：消融（T+30）—— 测试 AUC 与 准确率
fig, axes = plt.subplots(1, 2, figsize=(8.0, 3.4))
sub = abl_df[abl_df["horizon"] == "T+30"]
vnames = sub["variant"].tolist()
xa = np.arange(len(vnames)); ww = 0.36
axes[0].bar(xa, sub["test_auc"], ww, color="#8e44ad")
axes[0].axhline(0.5, color="#e67e22", ls="--", lw=1.2)
axes[0].set_xticks(xa); axes[0].set_xticklabels(vnames, rotation=20, ha="right", fontsize=7)
axes[0].set_ylim(0.4, 0.65); axes[0].set_title("T+30 Ablation: Test AUC", fontsize=9)
axes[1].bar(xa - ww/2, sub["test_accuracy"], ww, color="#c0392b", label="model")
axes[1].bar(xa + ww/2, sub["naive_accuracy"], ww, color="#7f8c8d", label="naive")
axes[1].set_xticks(xa); axes[1].set_xticklabels(vnames, rotation=20, ha="right", fontsize=7)
axes[1].set_ylim(0.4, 0.75); axes[1].set_title("T+30 Ablation: Accuracy", fontsize=9)
axes[1].legend(fontsize=7)
fig.suptitle("Ablation: GPR/EPU Marginal Contribution (T+30)", fontsize=10)
fig.tight_layout(); fig.savefig(FIG / "fig_ablation.png"); plt.close(fig)

# 图4：特征重要性（T+30 全特征）
fig, ax = plt.subplots(figsize=(6.2, 3.6))
imp_s = imp.sort_values("lgb_gain_pct", ascending=True)
ax.barh(imp_s["feature"], imp_s["lgb_gain_pct"], color="#16a085")
ax.set_xlabel("LightGBM gain (%)")
ax.set_title("Feature Importance (T+30, stationary full features)")
fig.tight_layout(); fig.savefig(FIG / "fig_importance.png"); plt.close(fig)

print("\n图表 & 汇总已保存至 reports/figures/ 与 analysis_summary.json")
print("DONE")
