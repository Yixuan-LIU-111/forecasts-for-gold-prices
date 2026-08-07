"""特征工程 —— 严格对齐《项目方案V1.0.md》第 9.4 章代码结构。

文档原文：
    df['return_30min']      = df['price'].pct_change(periods=30)
    df['volatility_30min']  = df['return_30min'].rolling(30).std()
    df['spread']            = df['high'] - df['low']
    df['sentiment_mean_30'] = df['sentiment_score'].rolling(30).mean()
    df['sentiment_max_30']  = df['sentiment_score'].rolling(30).max()
    df['hawkish_change']    = df['hawkish_score'].diff()
    df['dxy_return']        = df['dxy'].pct_change()
    df['tips_change']       = df['tips_yield'].diff()
    df['vix_level']         = df['vix']
    df['target']            = (df['price'].shift(-30) > df['price']).astype(int)

本实现的两点适配（已在报告中显式说明）：
1. bar 单位为「交易日」而非「分钟」（样本数据为日频），故 30 期 = 30 个交易日。
2. 情感 / 鹰鸽特征在历史样本中不存在，管道保留接入位但训练时自动跳过。

防前视偏差（Look-ahead Bias）约束：
- 所有特征仅使用 t 时刻及之前的信息（pct_change / rolling / diff 均为后视）
- 目标变量使用 t+HORIZON 的收盘价，训练时该行被视为「已知未来」，
  因此尾部 HORIZON 行必须丢弃，且划分严格按时间顺序、不打乱。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

import config as C


def build_features(df: pd.DataFrame, sentiment: pd.DataFrame | None = None,
                   horizon: int = C.HORIZON) -> pd.DataFrame:
    """由建模底表生成特征矩阵与目标变量。

    sentiment: 由 sentiment_features 产出的情感子表
               [date, sentiment_score, hawkish_score, news_count]，
               含则计算文档 §9.4 的情感/鹰鸽特征，否则跳过（训练降级）。
    """
    out = df.copy().sort_values("date").reset_index(drop=True)

    # ---------------- 价格序列特征（文档：价格序列） ----------------
    out["return_30"] = out["close"].pct_change(periods=C.ROLL_WINDOW)
    out["volatility_30"] = out["return_30"].rolling(C.ROLL_WINDOW).std()
    out["spread"] = out["high"] - out["low"]

    # ---------------- 市场特征（文档：市场特征） ----------------
    out["dxy_return"] = out["dxy"].pct_change()
    out["tips_change"] = out["tips"].diff()
    out["vix_level"] = out["vix"]

    # ---------------- 风险特征（样本额外提供，文档标记延后） ----------------
    out["gpr_level"] = out["gpr"]
    out["gpr_change"] = out["gpr"].diff()
    out["epu_level"] = out["epu"]
    out["epu_change"] = out["epu"].diff()

    # ---------------- 平稳化改造（v2） ----------------
    # 诊断依据：train→test 分布漂移 spread 5.19σ / epu_level 2.25σ /
    # gpr_level 1.33σ / volatility_30 1.24σ，绝对量纲在金价 1130→5446 区间失效。
    w = C.ZSCORE_WINDOW

    # 价差 → 相对价差（除以收盘价，消除价格量级影响）
    out["spread_pct"] = (out["high"] - out["low"]) / out["close"]

    # 波动率 → 短期/长期波动比（自归一化）
    long_vol = out["close"].pct_change().rolling(w).std()
    out["volatility_ratio"] = out["volatility_30"] / long_vol

    # 水平值 → 滚动 z-score（窗口内均值/标准差，仅回看）
    for src, dst in [("vix", "vix_z"), ("gpr", "gpr_z"), ("epu", "epu_z")]:
        mu = out[src].rolling(w).mean()
        sd = out[src].rolling(w).std()
        out[dst] = (out[src] - mu) / sd

    # 绝对变化量 → 相对变化率（对量级不敏感）
    out["gpr_change_pct"] = out["gpr"].pct_change()
    out["epu_change_pct"] = out["epu"].pct_change()

    out = out.replace([np.inf, -np.inf], np.nan)

    # ---------------- 情感 / 政策特征（LLM 情感 + 鹰鸽，§3.3/§9.4） ----------------
    out = attach_sentiment_features(out, sentiment)

    # ---------------- 目标变量（文档：shift(-30) 方向） ----------------
    out["target"] = (out["close"].shift(-horizon) > out["close"]).astype("Int64")

    # 辅助跨度目标（仅稳健性对照，不进入主模型）
    for h in C.AUX_HORIZONS:
        out[f"target_h{h}"] = (out["close"].shift(-h) > out["close"]).astype("Int64")

    return out


def attach_sentiment_features(df: pd.DataFrame,
                              sentiment: pd.DataFrame | None = None) -> pd.DataFrame:
    """接入 LLM 情感 / 鹰鸽特征（方案文档 §3.3 情感特征 + 政策特征 §9.4）。

    sentiment: 含 [date, sentiment_score, hawkish_score, news_count] 的 bar 对齐表，
               由 sentiment_features 模块产出。为 None 时本函数为 no-op，
               训练管道在无情感数据时仍可运行（对应文档「LLM 不可用时降级」）。

    计算文档 §9.4 指定特征（与 rolling(30) 窗口一致）：
      - sentiment_mean_30 / sentiment_max_30 : 情感分数的滚动均值 / 极值
      - hawkish_change                        : 鹰鸽立场的一阶差分（政策变化量）
    水平值 sentiment_score / hawkish_score 一并保留，作为模型可直接消费的瞬时特征。
    所有运算均仅回看历史，无前视偏差。
    """
    if sentiment is None:
        return df

    cols = [c for c in ("date", "sentiment_score", "hawkish_score", "news_count")
            if c in sentiment.columns]
    out = df.merge(sentiment[cols], on="date", how="left")
    # 无新闻的 bar：情感/立场视为中性 0（news_count 已为 0）
    out["sentiment_score"] = out["sentiment_score"].fillna(0.0)
    out["hawkish_score"] = out["hawkish_score"].fillna(0.0)
    if "news_count" in out.columns:
        out["news_count"] = out["news_count"].fillna(0).astype(int)

    out["sentiment_mean_30"] = out["sentiment_score"].rolling(C.ROLL_WINDOW).mean()
    out["sentiment_max_30"] = out["sentiment_score"].rolling(C.ROLL_WINDOW).max()
    out["hawkish_change"] = out["hawkish_score"].diff()
    out = out.replace([np.inf, -np.inf], np.nan)
    return out


def available_features(df: pd.DataFrame, feature_set: str) -> list[str]:
    """返回该数据集中实际可用的特征列（自动跳过缺失的情感特征）。"""
    wanted = list(C.FEATURE_SETS[feature_set])
    return [c for c in wanted if c in df.columns]


def make_xy(df: pd.DataFrame, feature_set: str = C.PRIMARY_FEATURE_SET,
            target_col: str = "target"):
    """产出建模用 (X, y, dates)。

    丢弃两类行：
    - 头部：滚动窗口未满导致的 NaN 特征
    - 尾部：shift(-horizon) 导致目标变量未知
    """
    feats = available_features(df, feature_set)
    sub = df[["date"] + feats + [target_col]].copy()
    sub = sub.dropna().reset_index(drop=True)

    X = sub[feats].astype(float)
    y = sub[target_col].astype(int)
    dates = sub["date"]
    return X, y, dates, feats


def chronological_split(X, y, dates,
                        train_ratio: float = C.TRAIN_RATIO,
                        valid_ratio: float = C.VALID_RATIO,
                        purge: int = C.PURGE_BARS):
    """按时间顺序划分 训练/验证/测试（文档 §9.5：70/15/15，不打乱）。

    额外施加 purge/embargo：目标变量看向 t+HORIZON，若不处理，
    前一段末尾 HORIZON 个样本的前瞻窗口会与后一段重叠，构成信息泄露。
    本函数在每个边界前剔除 `purge` 根 bar，保证各段标签窗口完全不相交。
    """
    n = len(X)
    i_tr = int(n * train_ratio)
    i_va = int(n * (train_ratio + valid_ratio))

    # 边界前剔除 purge 根 bar
    tr_end = max(0, i_tr - purge)
    va_end = max(tr_end, i_va - purge)

    def _slice(a, b):
        return (X.iloc[a:b], y.iloc[a:b], dates.iloc[a:b])

    return {
        "train": _slice(0, tr_end),
        "valid": _slice(i_tr, va_end),
        "test": _slice(i_va, n),
    }


if __name__ == "__main__":
    import data_loader

    base = data_loader.build_dataset(refresh=False, save=False)
    feat = build_features(base)
    feat.to_csv(C.FEATURES_CSV, index=False)

    X, y, dates, cols = make_xy(feat)
    parts = chronological_split(X, y, dates)

    print(f"特征列 ({len(cols)}): {cols}")
    print(f"有效样本: {len(X)}  (原始 {len(feat)}，剔除头部滚动NaN与尾部未知标签)")
    print(f"正类占比: {y.mean():.4f}")
    print()
    for name, (Xs, ys, ds) in parts.items():
        print(f"{name:6s} n={len(Xs):5d}  {ds.min().date()} ~ {ds.max().date()}  "
              f"正类占比={ys.mean():.4f}")
