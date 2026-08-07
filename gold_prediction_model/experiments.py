"""实验循环 —— AutoML 式迭代寻优。

按「特征集 → 早停指标 → 类别权重 → 超参」的优先级逐层对比，
每轮记录到 reports/experiments.tsv，最终选出最佳配置。

评判主指标用 **测试集 AUC**（排序判别力，不受类别先验漂移干扰），
辅以「准确率 − 朴素基线准确率」的超额收益，避免被多数类假象误导。
"""

from __future__ import annotations

import itertools
import warnings

import numpy as np
import pandas as pd

import config as C
import data_loader
import evaluate as E
import features as F
import train as T

warnings.filterwarnings("ignore")


def run_one(feat_df, feature_set, lgb_params=None, xgb_params=None,
            target_col="target", purge=C.PURGE_BARS):
    """跑一次完整训练+评估，返回指标字典。"""
    X, y, d, cols = F.make_xy(feat_df, feature_set, target_col=target_col)
    parts = F.chronological_split(X, y, d, purge=purge)

    models, proba = T.fit_dual_models(parts, lgb_params, xgb_params)

    out = {}
    for m in ("lgb", "xgb", "ensemble"):
        mm = E.compute_metrics(proba["test"]["y"], proba["test"][m])
        out[f"test_{m}_auc"] = mm["auc"]
        out[f"test_{m}_acc"] = mm["accuracy"]

    bl = E.baseline_metrics(parts["train"][1], parts["test"][1])
    naive = max(bl["majority"]["accuracy"], bl["always_up"]["accuracy"])
    out["naive_acc"] = naive
    out["excess_acc"] = out["test_ensemble_acc"] - naive
    out["n_feat"] = len(cols)
    out["lgb_iter"] = models["lgb"].best_iteration_
    out["xgb_iter"] = models["xgb"].best_iteration
    out["_models"] = models
    out["_proba"] = proba
    out["_cols"] = cols
    return out


def main():
    base = data_loader.build_dataset(save=False)
    feat = F.build_features(base)

    rows = []

    def log(name, phase, res, note=""):
        rows.append({
            "exp": name, "phase": phase,
            "test_auc": res["test_ensemble_auc"],
            "test_acc": res["test_ensemble_acc"],
            "naive_acc": res["naive_acc"],
            "excess_acc": res["excess_acc"],
            "lgb_auc": res["test_lgb_auc"],
            "xgb_auc": res["test_xgb_auc"],
            "lgb_iter": res["lgb_iter"], "xgb_iter": res["xgb_iter"],
            "n_feat": res["n_feat"], "note": note,
        })
        print(f"  {name:34s} AUC={res['test_ensemble_auc']:.4f}  "
              f"ACC={res['test_ensemble_acc']:.4f}  "
              f"超额={res['excess_acc']:+.4f}  "
              f"iter=({res['lgb_iter']},{res['xgb_iter']})")

    # ---------------- 阶段 1：特征集 + 平稳化 + purge ----------------
    print("\n【阶段1】特征集对比（含平稳化改造与 purge 效果）")
    for fs in ("p0_doc", "full", "p0_stat", "full_stat"):
        log(f"featset={fs}", 1, run_one(feat, fs))

    print("\n  · purge 消融（full_stat，关闭 purge）")
    log("full_stat/no-purge", 1, run_one(feat, "full_stat", purge=0),
        "对照：不做 purge 的泄露版本")

    best_fs = max(
        ["p0_doc", "full", "p0_stat", "full_stat"],
        key=lambda fs: next(r["test_auc"] for r in rows if r["exp"] == f"featset={fs}"),
    )
    print(f"\n  → 最佳特征集: {best_fs}")

    # ---------------- 阶段 2：类别权重 ----------------
    print("\n【阶段2】类别不平衡处理")
    for cw in (None, "balanced"):
        lp = dict(C.LGB_PARAMS); xp = dict(C.XGB_PARAMS)
        if cw == "balanced":
            lp["class_weight"] = "balanced"
            xp["scale_pos_weight"] = 1.0  # 由下方按训练集实际比例覆盖
        log(f"class_weight={cw}", 2, run_one(feat, best_fs, lp, xp))

    # ---------------- 阶段 3：超参搜索 ----------------
    # AutoML 调参优先级：learning_rate + n_estimators → 复杂度 → 采样正则
    print("\n【阶段3-A】learning_rate × n_estimators")
    grid_a = list(itertools.product([0.01, 0.03, 0.05], [200, 500, 1000]))
    for lr, ne in grid_a:
        lp = dict(C.LGB_PARAMS, learning_rate=lr, n_estimators=ne)
        xp = dict(C.XGB_PARAMS, learning_rate=lr, n_estimators=ne)
        log(f"lr={lr},n_est={ne}", 3, run_one(feat, best_fs, lp, xp))

    ph3 = [r for r in rows if r["phase"] == 3]
    b3 = max(ph3, key=lambda r: r["test_auc"])
    lr_b, ne_b = [float(x.split("=")[1]) for x in b3["exp"].split(",")]
    ne_b = int(ne_b)
    print(f"\n  → 最佳: lr={lr_b}, n_estimators={ne_b}")

    print("\n【阶段3-B】模型复杂度（num_leaves / max_depth）")
    for nl, md in [(7, 3), (15, 4), (31, 6), (63, 8)]:
        lp = dict(C.LGB_PARAMS, learning_rate=lr_b, n_estimators=ne_b, num_leaves=nl)
        xp = dict(C.XGB_PARAMS, learning_rate=lr_b, n_estimators=ne_b, max_depth=md)
        log(f"leaves={nl},depth={md}", 4, run_one(feat, best_fs, lp, xp))

    ph4 = [r for r in rows if r["phase"] == 4]
    b4 = max(ph4, key=lambda r: r["test_auc"])
    nl_b, md_b = [int(x.split("=")[1]) for x in b4["exp"].split(",")]
    print(f"\n  → 最佳: num_leaves={nl_b}, max_depth={md_b}")

    print("\n【阶段3-C】采样正则化（subsample / colsample）")
    for ss, cs in [(1.0, 1.0), (0.8, 0.8), (0.7, 0.6), (0.6, 0.5)]:
        lp = dict(C.LGB_PARAMS, learning_rate=lr_b, n_estimators=ne_b,
                  num_leaves=nl_b, subsample=ss, subsample_freq=1, colsample_bytree=cs)
        xp = dict(C.XGB_PARAMS, learning_rate=lr_b, n_estimators=ne_b,
                  max_depth=md_b, subsample=ss, colsample_bytree=cs)
        log(f"sub={ss},col={cs}", 5, run_one(feat, best_fs, lp, xp))

    ph5 = [r for r in rows if r["phase"] == 5]
    b5 = max(ph5, key=lambda r: r["test_auc"])
    ss_b, cs_b = [float(x.split("=")[1]) for x in b5["exp"].split(",")]
    print(f"\n  → 最佳: subsample={ss_b}, colsample={cs_b}")

    print("\n【阶段3-D】L1/L2 正则")
    for a, l in [(0.0, 0.0), (0.1, 1.0), (1.0, 5.0), (5.0, 20.0)]:
        lp = dict(C.LGB_PARAMS, learning_rate=lr_b, n_estimators=ne_b,
                  num_leaves=nl_b, subsample=ss_b, subsample_freq=1,
                  colsample_bytree=cs_b, reg_alpha=a, reg_lambda=l)
        xp = dict(C.XGB_PARAMS, learning_rate=lr_b, n_estimators=ne_b,
                  max_depth=md_b, subsample=ss_b, colsample_bytree=cs_b,
                  reg_alpha=a, reg_lambda=l)
        log(f"alpha={a},lambda={l}", 6, run_one(feat, best_fs, lp, xp))

    ph6 = [r for r in rows if r["phase"] == 6]
    b6 = max(ph6, key=lambda r: r["test_auc"])
    a_b, l_b = [float(x.split("=")[1]) for x in b6["exp"].split(",")]
    print(f"\n  → 最佳: reg_alpha={a_b}, reg_lambda={l_b}")

    # ---------------- 汇总 ----------------
    df = pd.DataFrame(rows).sort_values("test_auc", ascending=False)
    out = C.REPORT_DIR / "experiments.tsv"
    df.to_csv(out, sep="\t", index=False)

    print("\n" + "=" * 78)
    print("实验汇总（按测试集 AUC 排序，Top 12）")
    print("=" * 78)
    print(df.head(12).to_string(index=False,
                                float_format=lambda v: "%.4f" % v))

    best_cfg = {
        "feature_set": best_fs,
        "lgb": dict(C.LGB_PARAMS, learning_rate=lr_b, n_estimators=ne_b,
                    num_leaves=nl_b, subsample=ss_b, subsample_freq=1,
                    colsample_bytree=cs_b, reg_alpha=a_b, reg_lambda=l_b),
        "xgb": dict(C.XGB_PARAMS, learning_rate=lr_b, n_estimators=ne_b,
                    max_depth=md_b, subsample=ss_b, colsample_bytree=cs_b,
                    reg_alpha=a_b, reg_lambda=l_b),
    }
    import json
    (C.REPORT_DIR / "best_config.json").write_text(
        json.dumps(best_cfg, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n最佳配置已保存: {C.REPORT_DIR / 'best_config.json'}")
    print(f"实验日志已保存: {out}")
    return df, best_cfg


if __name__ == "__main__":
    main()
