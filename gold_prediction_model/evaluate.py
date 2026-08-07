"""模型评估 —— 准确率 / F1 / AUC / LogLoss + 过拟合检测 + 基线对照。

对齐《项目方案V1.0.md》§9.5「评估指标：准确率、F1、AUC、对数损失」
以及「过拟合检测：训练集与测试集准确率差异 > 15% 告警」。
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.metrics import (
    accuracy_score, f1_score, log_loss, precision_score,
    recall_score, roc_auc_score, confusion_matrix,
)

import config as C


def compute_metrics(y_true, p_pred, threshold: float = 0.5) -> dict:
    """核心四项指标 + 精确率/召回率。"""
    y_true = np.asarray(y_true).astype(int)
    p_pred = np.clip(np.asarray(p_pred, dtype=float), 1e-6, 1 - 1e-6)
    y_hat = (p_pred >= threshold).astype(int)

    # AUC 在单一类别时无定义
    try:
        auc = roc_auc_score(y_true, p_pred) if len(np.unique(y_true)) > 1 else float("nan")
    except ValueError:
        auc = float("nan")

    return {
        "accuracy": accuracy_score(y_true, y_hat),
        "f1": f1_score(y_true, y_hat, zero_division=0),
        "auc": auc,
        "logloss": log_loss(y_true, p_pred, labels=[0, 1]),
        "precision": precision_score(y_true, y_hat, zero_division=0),
        "recall": recall_score(y_true, y_hat, zero_division=0),
    }


def baseline_metrics(y_train, y_test) -> dict:
    """基线对照，用于判断模型是否真的有增量价值。

    - majority : 恒定预测训练集多数类
    - always_up: 恒定预测「上涨」（对应买入持有，文档 F11 要求与买入持有对比）
    - prior    : 用训练集正类先验作为恒定概率（评估 logloss 的合理下界）
    """
    y_train = np.asarray(y_train).astype(int)
    y_test = np.asarray(y_test).astype(int)

    maj = int(round(y_train.mean()))
    prior = float(np.clip(y_train.mean(), 1e-6, 1 - 1e-6))

    return {
        "majority": compute_metrics(y_test, np.full(len(y_test), float(maj))),
        "always_up": compute_metrics(y_test, np.full(len(y_test), 1.0 - 1e-6)),
        "prior": compute_metrics(y_test, np.full(len(y_test), prior)),
        "_majority_class": maj,
        "_train_prior": prior,
        "_test_pos_rate": float(y_test.mean()),
    }


def evaluate_all_splits(proba: dict) -> pd.DataFrame:
    """对 train/valid/test × lgb/xgb/ensemble 全量出指标。"""
    rows = []
    for split in ("train", "valid", "test"):
        if split not in proba:
            continue
        d = proba[split]
        for model in ("lgb", "xgb", "ensemble"):
            m = compute_metrics(d["y"], d[model])
            m.update({"split": split, "model": model, "n": len(d["y"])})
            rows.append(m)

    df = pd.DataFrame(rows)
    return df[["split", "model", "n", "accuracy", "f1", "auc",
               "logloss", "precision", "recall"]]


def overfit_check(metrics_df: pd.DataFrame,
                  threshold: float = C.OVERFIT_GAP_THRESHOLD) -> dict:
    """过拟合检测（文档 §9.5：训练/测试准确率差异 > 15% 告警）。"""
    res = {}
    for model in ("lgb", "xgb", "ensemble"):
        try:
            tr = metrics_df.query("split=='train' and model==@model")["accuracy"].iloc[0]
            te = metrics_df.query("split=='test'  and model==@model")["accuracy"].iloc[0]
        except IndexError:
            continue
        gap = tr - te
        res[model] = {
            "train_acc": tr,
            "test_acc": te,
            "gap": gap,
            "alert": bool(gap > threshold),
        }
    return res


def confusion(y_true, p_pred, threshold: float = 0.5) -> pd.DataFrame:
    y_hat = (np.asarray(p_pred) >= threshold).astype(int)
    cm = confusion_matrix(np.asarray(y_true).astype(int), y_hat, labels=[0, 1])
    return pd.DataFrame(
        cm,
        index=["实际:下跌", "实际:上涨"],
        columns=["预测:下跌", "预测:上涨"],
    )


def signal_rule_evaluation(y_true, p_pred) -> pd.DataFrame:
    """按文档 §10.1 信号生成规则评估「实际发出信号」的准确率。

    文档规则（置信度以 |p-0.5|*2 近似）：
        P > 0.60 → 看涨 ；P < 0.40 → 看跌 ；其余 → 观望
    观望不计入准确率分母，对应文档「无信号期间分母为零显示数据不足」。
    """
    y_true = np.asarray(y_true).astype(int)
    p = np.asarray(p_pred, dtype=float)

    rows = []
    for lo, hi, label in [(0.40, 0.60, "全部信号(P>0.6 或 P<0.4)"),
                          (0.30, 0.70, "强信号(P>0.7 或 P<0.3)")]:
        bull = p > hi
        bear = p < lo
        act = bull | bear
        n = int(act.sum())
        if n == 0:
            rows.append({"信号档位": label, "触发次数": 0, "覆盖率": 0.0,
                         "方向准确率": float("nan")})
            continue
        pred = np.where(bull[act], 1, 0)
        acc = float((pred == y_true[act]).mean())
        rows.append({
            "信号档位": label,
            "触发次数": n,
            "覆盖率": n / len(p),
            "方向准确率": acc,
        })
    return pd.DataFrame(rows)
