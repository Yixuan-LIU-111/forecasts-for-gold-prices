"""模型选择 —— 严格无测试集泄露。

方法论：
  开发集 = 前 85%（对应文档的 train 70% + valid 15%）
  测试集 = 后 15%，全程隔离，仅在最终评估时使用一次

  超参与特征集的选择，全部基于「开发集内部的 purged walk-forward CV」平均 AUC。
  这修正了朴素做法（按测试集表现挑参数）造成的选择性泄露。

调参优先级遵循 AutoML 惯例：
  特征集 → learning_rate → 复杂度 → 采样正则 → L1/L2
"""

from __future__ import annotations

import itertools
import json
import warnings

import numpy as np
import pandas as pd

import config as C
import data_loader
import evaluate as E
import features as F
import train as T

warnings.filterwarnings("ignore")


def dev_test_split(X, y, d, dev_ratio=C.TRAIN_RATIO + C.VALID_RATIO,
                   purge=C.PURGE_BARS):
    """开发集 / 测试集划分，边界做 purge。"""
    n = len(X)
    i = int(n * dev_ratio)
    dev_end = max(0, i - purge)
    return (
        (X.iloc[:dev_end], y.iloc[:dev_end], d.iloc[:dev_end]),
        (X.iloc[i:], y.iloc[i:], d.iloc[i:]),
    )


def cv_eval(feat, feature_set, lgb_params=None, xgb_params=None,
            target_col="target"):
    """返回该配置在开发集 CV 上的 (最优树数, 平均AUC)。"""
    X, y, d, cols = F.make_xy(feat, feature_set, target_col=target_col)
    (Xd, yd, dd), _ = dev_test_split(X, y, d)
    return T.purged_cv_score(Xd, yd, lgb_params, xgb_params)


def run(target_col="target", horizon_label="T+30"):
    base = data_loader.build_dataset(save=False)
    feat = F.build_features(base)

    trials = []

    def log(name, phase, ne, auc):
        trials.append({"exp": name, "phase": phase,
                       "best_n_estimators": ne, "cv_auc": auc})
        print(f"  {name:32s} CV_AUC={auc:.4f}  n_est={ne}")

    print(f"\n{'='*78}\n模型选择 · 预测跨度 {horizon_label} "
          f"(仅用开发集 CV，测试集隔离)\n{'='*78}")

    # ---------- 阶段 1：特征集 ----------
    print("\n【1】特征集")
    fs_res = {}
    for fs in ("p0_doc", "full", "p0_stat", "full_stat"):
        ne, auc = cv_eval(feat, fs, target_col=target_col)
        fs_res[fs] = auc
        log(f"featset={fs}", 1, ne, auc)
    best_fs = max(fs_res, key=lambda k: fs_res[k])
    print(f"  → 选定特征集: {best_fs}")

    # ---------- 阶段 2：learning_rate ----------
    print("\n【2】learning_rate")
    lr_res = {}
    for lr in (0.01, 0.02, 0.05, 0.1):
        lp = dict(C.LGB_PARAMS, learning_rate=lr)
        xp = dict(C.XGB_PARAMS, learning_rate=lr)
        ne, auc = cv_eval(feat, best_fs, lp, xp, target_col)
        lr_res[lr] = (auc, ne)
        log(f"lr={lr}", 2, ne, auc)
    best_lr = max(lr_res, key=lambda k: lr_res[k][0])
    print(f"  → 选定 learning_rate={best_lr}")

    # ---------- 阶段 3：复杂度 ----------
    print("\n【3】模型复杂度")
    cx_res = {}
    for nl, md in [(3, 2), (7, 3), (15, 4), (31, 6)]:
        lp = dict(C.LGB_PARAMS, learning_rate=best_lr, num_leaves=nl,
                  min_child_samples=40)
        xp = dict(C.XGB_PARAMS, learning_rate=best_lr, max_depth=md,
                  min_child_weight=10)
        ne, auc = cv_eval(feat, best_fs, lp, xp, target_col)
        cx_res[(nl, md)] = (auc, ne)
        log(f"leaves={nl},depth={md}", 3, ne, auc)
    best_nl, best_md = max(cx_res, key=lambda k: cx_res[k][0])
    print(f"  → 选定 num_leaves={best_nl}, max_depth={best_md}")

    # ---------- 阶段 4：采样正则 ----------
    print("\n【4】采样正则化")
    sp_res = {}
    for ss, cs in [(1.0, 1.0), (0.9, 0.9), (0.8, 0.7), (0.7, 0.5)]:
        lp = dict(C.LGB_PARAMS, learning_rate=best_lr, num_leaves=best_nl,
                  min_child_samples=40, subsample=ss, subsample_freq=1,
                  colsample_bytree=cs)
        xp = dict(C.XGB_PARAMS, learning_rate=best_lr, max_depth=best_md,
                  min_child_weight=10, subsample=ss, colsample_bytree=cs)
        ne, auc = cv_eval(feat, best_fs, lp, xp, target_col)
        sp_res[(ss, cs)] = (auc, ne)
        log(f"sub={ss},col={cs}", 4, ne, auc)
    best_ss, best_cs = max(sp_res, key=lambda k: sp_res[k][0])
    print(f"  → 选定 subsample={best_ss}, colsample={best_cs}")

    # ---------- 阶段 5：L1/L2 ----------
    print("\n【5】L1/L2 正则")
    rg_res = {}
    for a, l in [(0.0, 0.0), (0.1, 1.0), (1.0, 10.0)]:
        lp = dict(C.LGB_PARAMS, learning_rate=best_lr, num_leaves=best_nl,
                  min_child_samples=40, subsample=best_ss, subsample_freq=1,
                  colsample_bytree=best_cs, reg_alpha=a, reg_lambda=l)
        xp = dict(C.XGB_PARAMS, learning_rate=best_lr, max_depth=best_md,
                  min_child_weight=10, subsample=best_ss,
                  colsample_bytree=best_cs, reg_alpha=a, reg_lambda=l)
        ne, auc = cv_eval(feat, best_fs, lp, xp, target_col)
        rg_res[(a, l)] = (auc, ne)
        log(f"alpha={a},lambda={l}", 5, ne, auc)
    best_a, best_l = max(rg_res, key=lambda k: rg_res[k][0])
    print(f"  → 选定 reg_alpha={best_a}, reg_lambda={best_l}")

    # ---------- 最终配置 ----------
    lgb_best = dict(C.LGB_PARAMS, learning_rate=best_lr, num_leaves=best_nl,
                    min_child_samples=40, subsample=best_ss, subsample_freq=1,
                    colsample_bytree=best_cs, reg_alpha=best_a, reg_lambda=best_l)
    xgb_best = dict(C.XGB_PARAMS, learning_rate=best_lr, max_depth=best_md,
                    min_child_weight=10, subsample=best_ss,
                    colsample_bytree=best_cs, reg_alpha=best_a, reg_lambda=best_l)
    final_ne, final_auc = cv_eval(feat, best_fs, lgb_best, xgb_best, target_col)

    cfg = {
        "target_col": target_col,
        "horizon_label": horizon_label,
        "feature_set": best_fs,
        "n_estimators": final_ne,
        "cv_auc": final_auc,
        "lgb_params": lgb_best,
        "xgb_params": xgb_best,
    }
    print(f"\n最终配置 CV_AUC={final_auc:.4f}, n_estimators={final_ne}")

    df = pd.DataFrame(trials).sort_values("cv_auc", ascending=False)
    return cfg, df


def final_evaluate(cfg):
    """用选定配置在开发集上拟合，在测试集上评估一次。"""
    base = data_loader.build_dataset(save=False)
    feat = F.build_features(base)
    X, y, d, cols = F.make_xy(feat, cfg["feature_set"],
                              target_col=cfg["target_col"])
    (Xd, yd, dd), (Xt, yt, dt) = dev_test_split(X, y, d)

    models = T.fit_fixed(Xd, yd, cfg["lgb_params"], cfg["xgb_params"],
                         cfg["n_estimators"], cfg["n_estimators"])

    proba = {}
    for nm, (Xs, ys, ds) in (("dev", (Xd, yd, dd)), ("test", (Xt, yt, dt))):
        pl = models["lgb"].predict_proba(Xs)[:, 1]
        px = models["xgb"].predict_proba(Xs)[:, 1]
        proba[nm] = {"lgb": pl, "xgb": px,
                     "ensemble": T.ensemble_proba(pl, px),
                     "y": ys.to_numpy(), "dates": ds.reset_index(drop=True)}
    return models, proba, cols, (Xd, yd, dd), (Xt, yt, dt)


if __name__ == "__main__":
    all_cfg = {}
    for tc, lbl in [("target", "T+30"), ("target_h5", "T+5"), ("target_h1", "T+1")]:
        cfg, trials = run(tc, lbl)
        models, proba, cols, dev, test = final_evaluate(cfg)

        m = E.compute_metrics(proba["test"]["y"], proba["test"]["ensemble"])
        bl = E.baseline_metrics(dev[1], test[1])
        naive = max(bl["majority"]["accuracy"], bl["always_up"]["accuracy"])

        print(f"\n>>> {lbl} 测试集最终结果（仅评估一次）")
        print(f"    accuracy={m['accuracy']:.4f}  朴素基线={naive:.4f}  "
              f"超额={m['accuracy']-naive:+.4f}")
        print(f"    auc={m['auc']:.4f}  f1={m['f1']:.4f}  "
              f"logloss={m['logloss']:.4f}")

        cfg["test_metrics"] = m
        cfg["naive_acc"] = naive
        all_cfg[lbl] = cfg
        trials.to_csv(C.REPORT_DIR / f"selection_{lbl.replace('+','')}.tsv",
                      sep="\t", index=False)

    (C.REPORT_DIR / "selected_configs.json").write_text(
        json.dumps(all_cfg, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8")
    print(f"\n配置已保存: {C.REPORT_DIR / 'selected_configs.json'}")
