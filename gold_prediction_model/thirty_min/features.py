"""特征工程 —— 技术指标 + LLM 情感聚合 + 宏观因子（固定 30 分钟窗口）。

防前视偏差（look-ahead）约束：
- 所有特征仅使用 t 时刻及之前的信息（pct_change / rolling / diff 均为后视）。
- 目标变量使用 t+1 根 bar 的收盘价，训练时尾部 HORIZON_BARS 行必须丢弃。
- 情感聚合特征在 data_layer 已按「≤事件时刻」对齐，此处仅做滚动统计；
  窗口回望 [t-W+1, t]，绝不触及未来。

对应需求 2：在技术指标基础上加入情感聚合特征
（窗口内情感均值 / 极值 / 密度 / 置信加权均值）。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from . import config


def build_features(df: pd.DataFrame, horizon_bars: int = config.HORIZON_BARS) -> pd.DataFrame:
    """由建模底表生成特征矩阵与目标变量（index=bar_start）。"""
    if df.empty:
        return df

    out = df.copy().sort_index()

    # ---------------- 价格技术指标（30 分钟，后视） ----------------
    out["ret_1"] = out["close"].pct_change(1)
    out["log_ret"] = np.log(out["close"] / out["close"].shift(1))
    out["ret_vol"] = out["ret_1"].rolling(config.VOL_WINDOW_BARS).std()
    ma = out["close"].rolling(config.MA_WINDOW_BARS).mean()
    out["ma_dev"] = out["close"] / ma - 1.0
    out["range_pct"] = (out["high"] - out["low"]) / out["close"]

    # 新增：更强的短周期技术特征（30m 微观结构信号）
    # RSI（14 根 bar）
    delta = out["close"].diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rs = gain / (loss + 1e-9)
    out["rsi"] = 100 - 100 / (1 + rs)
    # 波动率 z 分数（体制自适应）：当前波动相对近 96 根 bar 均值
    vol_long = out["ret_vol"].rolling(96).mean()
    vol_sd = out["ret_vol"].rolling(96).std()
    out["vol_z"] = (out["ret_vol"] - vol_long) / (vol_sd + 1e-9)
    # 收益 z 分数（体制自适应）
    ret_mean = out["ret_1"].rolling(96).mean()
    ret_sd = out["ret_1"].rolling(96).std()
    out["ret_z"] = (out["ret_1"] - ret_mean) / (ret_sd + 1e-9)
    # 长周期 MA 偏离（96 根 ≈ 2 日）
    ma_long = out["close"].rolling(96).mean()
    out["ma_dev_long"] = out["close"] / ma_long - 1.0
    # 成交量代理（采样密度）
    if "sampling_count" in out.columns:
        out["sampling_count"] = out["sampling_count"].astype(float)

    # ---------------- 情感聚合特征（已在 data_layer 按窗口对齐） ----------------
    # 注意：data_layer 已对每根 bar 计算了「过去 W 根 bar 窗口内」的
    # 情感均值/极值/密度/置信加权均值，这里**不再二次 rolling**，
    # 仅把无新闻窗口（NaN）补 0，保持 has_news 为 0/1 指示。
    if "sent_mean" in out.columns:
        for c in ("sent_mean", "sent_absmax", "sent_std", "news_density", "sent_conf_mean"):
            out[c] = out[c].fillna(0.0)
        out["has_news"] = out.get("has_news", 0).fillna(0).astype(int)
    else:
        for c in config.FEATURES_SENTIMENT:
            out[c] = 0.0

    # ---------------- 新闻压力代理（真实 GPR/EPU 量化情感） ----------------
    # 由 data_layer 对齐到 30m 的 gpr_news_sent / epu_news_sent；
    # 组合为综合宏观新闻情感，并取近 96 根 bar 滚动均值捕捉情绪持续度。
    if "gpr_news_sent" in out.columns:
        out["gpr_news_sent"] = out["gpr_news_sent"].fillna(0.0)
        out["epu_news_sent"] = out.get("epu_news_sent", 0.0).fillna(0.0)
        out["macro_news_sent"] = ((out["gpr_news_sent"] + out["epu_news_sent"]) / 2.0).clip(-1, 1)
        out["macro_news_sent_roll"] = out["macro_news_sent"].rolling(96).mean().fillna(0.0)
    else:
        for c in ("gpr_news_sent", "epu_news_sent", "macro_news_sent", "macro_news_sent_roll"):
            out[c] = 0.0

    # ---------------- 宏观因子特征（日频 ffill，已前视安全） ----------------
    if "dxy" in out.columns:
        out["dxy_return"] = out["dxy"].pct_change()
    if "vix" in out.columns:
        out["vix_level"] = out["vix"]
        out["vix_change"] = out["vix"].diff()
    if "tips" in out.columns:
        out["tips_change"] = out["tips"].diff()

    out = out.replace([np.inf, -np.inf], np.nan)

    # ---------------- 目标变量：未来 1 根 bar（=30 分钟）方向 ----------------
    # 涨 → 1，跌/平 → 0。对应硬约束：固定 30 分钟窗口。
    future_close = out["close"].shift(-horizon_bars)
    out["target"] = (future_close > out["close"]).astype("Int64")

    return out


def available_features(df: pd.DataFrame, feature_set: str = config.PRIMARY_FEATURE_SET) -> list[str]:
    """返回数据集中实际可用的特征列（自动跳过缺失列）。"""
    if feature_set == "all":
        wanted = list(config.FEATURES_ALL)
    elif feature_set == "no_sentiment":
        wanted = list(config.FEATURES_NO_SENTIMENT)
    else:
        wanted = list(config.FEATURES_ALL)
    return [c for c in wanted if c in df.columns]


def make_xy(df: pd.DataFrame, feature_set: str = config.PRIMARY_FEATURE_SET,
            target_col: str = "target"):
    """产出建模用 (X, y, dates, feature_cols)。

    丢弃：全 NaN 的特征列（如合成数据时段无宏观因子）、
    头部滚动窗口未满的 NaN 特征、尾部目标变量未知的行。
    """
    feats = available_features(df, feature_set)
    # 丢弃整列为 NaN 的特征（例如合成数据 timeframe 与真实因子不重叠时）
    present = [c for c in feats if df[c].notna().any()]
    dropped = [c for c in feats if c not in present]
    if dropped:
        import logging
        logging.getLogger("thirty_min.features").info("跳过全 NaN 特征列: %s", dropped)
    sub = df[present + [target_col]].copy()
    sub = sub.dropna().reset_index(drop=False)
    X = sub[present].astype(float)
    y = sub[target_col].astype(int)
    dates = sub["bar_start"]
    return X, y, dates, present
