"""预处理模块 —— 合并、清洗、缺失值处理、特征工程、标准格式落盘。

流程（preprocess.run）：
  1. merge        ：以黄金交易日为基准，宏观指标按日期 left-join（前向填充，无后视）
  2. clean        ：类型强转、去重、按日期排序、基础异常剔除
  3. handle_missing：宏观指标 ffill→bfill→线性插值；关键列仍缺失则剔除行首
  4. engineer     ：复用 features.build_features 做特征工程（含目标变量 shift(-HORIZON)）
  5. save_standard：落盘为标准 CSV（特征底表 + 建模底表）

所有步骤均保持时间顺序、禁止未来信息泄漏。
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

import config as C
import features as F


def merge(gold: pd.DataFrame, macro: pd.DataFrame) -> pd.DataFrame:
    """对齐黄金价格与宏观指标，输出建模底表。"""
    if "date" not in gold.columns or "date" not in macro.columns:
        raise ValueError("gold / macro 必须含 date 列")
    df = gold.merge(macro, on="date", how="left")
    macro_cols = list(C.INDICATOR_MAP.values())
    df[macro_cols] = df[macro_cols].ffill()  # 仅向前填充，不使用未来信息
    return df


def clean(df: pd.DataFrame) -> pd.DataFrame:
    """清洗：类型强转、去重、排序、剔除无价格/无日期行。"""
    out = df.copy()
    out["date"] = pd.to_datetime(out["date"], errors="coerce")
    for c in ("open", "high", "low", "close"):
        if c in out.columns:
            out[c] = pd.to_numeric(out[c], errors="coerce")
    for c in C.INDICATOR_MAP.values():
        if c in out.columns:
            out[c] = pd.to_numeric(out[c], errors="coerce")
    out = out.dropna(subset=["date", "close"])
    out = out.drop_duplicates(subset=["date"]).sort_values("date").reset_index(drop=True)
    # 基础合理性：close>0，high>=low
    out = out[(out["close"] > 0)]
    if "high" in out.columns and "low" in out.columns:
        out = out[out["high"] >= out["low"]]
    return out


def handle_missing(df: pd.DataFrame,
                   macro_cols: Optional[list[str]] = None,
                   max_ffill_gap: int = 7) -> pd.DataFrame:
    """缺失值处理：宏观指标 ffill→bfill→插值；缺口过大则标记。"""
    out = df.copy()
    macro_cols = macro_cols or list(C.INDICATOR_MAP.values())
    present = [c for c in macro_cols if c in out.columns]

    # 前向填充（非交易日宏观缺失用最近已知值）
    out[present] = out[present].ffill(limit=max_ffill_gap)
    out[present] = out[present].bfill(limit=max_ffill_gap)
    # 仍存在的少量缺口用线性插值补齐
    out[present] = out[present].interpolate(method="linear", limit_direction="both")

    # 开头若仍有宏观缺失（无历史可填），剔除对应行首
    before = len(out)
    out = out.dropna(subset=present).reset_index(drop=True)
    if len(out) < before:
        print(f"[preprocess] 剔除开头宏观缺失行：{before - len(out)} 行")
    return out


def engineer(df: pd.DataFrame, horizon: int = C.HORIZON,
             sentiment: pd.DataFrame | None = None) -> pd.DataFrame:
    """特征工程（复用 features.build_features，可注入 LLM 情感/鹰鸽子表）。"""
    return F.build_features(df, sentiment=sentiment, horizon=horizon)


def save_standard(features_df: pd.DataFrame, merged_df: pd.DataFrame,
                  out_dir: Path = C.DATA_DIR) -> dict:
    """落盘为标准格式 CSV。"""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    feat_path = out_dir / "features_standard.csv"
    merge_path = out_dir / "dataset_standard.csv"
    features_df.to_csv(feat_path, index=False)
    merged_df.to_csv(merge_path, index=False)
    return {"features_csv": str(feat_path), "dataset_csv": str(merge_path)}


def run(gold: pd.DataFrame, macro: pd.DataFrame,
        horizon: int = C.HORIZON, sentiment: pd.DataFrame | None = None,
        save: bool = True, out_dir: Path = C.DATA_DIR) -> pd.DataFrame:
    """端到端预处理：合并→清洗→缺失处理→特征工程→（可选）落盘。"""
    print("[preprocess] 合并 …")
    merged = merge(gold, macro)
    print(f"           合并后 {len(merged)} 行，字段: {list(merged.columns)}")

    print("[preprocess] 清洗 …")
    merged = clean(merged)

    print("[preprocess] 缺失值处理 …")
    merged = handle_missing(merged)

    has_sent = sentiment is not None
    print(f"[preprocess] 特征工程（horizon={horizon}，"
          f"情感特征={'启用' if has_sent else '未注入（降级）'}）…")
    feats = engineer(merged, horizon=horizon, sentiment=sentiment)
    print(f"           特征底表 {len(feats)} 行，"
          f"样本中值标签占比 {feats['target'].astype(float).mean():.3f}")

    if save:
        paths = save_standard(feats, merged, out_dir=out_dir)
        print(f"[preprocess] 已保存标准格式: {paths}")
    return feats


if __name__ == "__main__":
    import collector as CL
    g, m = CL.MarketCollector().collect_all()
    feat = run(g, m, save=True)
    print(feat.tail())
