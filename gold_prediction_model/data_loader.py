"""数据加载与对齐。

职责：
1. 解析 docs/data_sample 的 Excel 样本（VIX / GPR / EPU / DXY / TIPS，日频）
2. 抓取并缓存 COMEX 黄金日线 OHLC（目标变量所需，样本数据未提供）
3. 按交易日对齐合并，落盘为建模底表

可复现性：抓取结果缓存到 data/gold_gc_daily_raw.csv，二次运行默认读缓存；
用 --refresh 强制重新抓取。
"""

from __future__ import annotations

import json
import re
import urllib.request
from datetime import datetime

import numpy as np
import pandas as pd

import config as C


# ------------------------------------------------------------------ 宏观指标
def load_macro_sample() -> pd.DataFrame:
    """读取 Excel 样本数据，返回日频宏观指标宽表。

    Excel 结构：前 5 行为元信息（指标简称/频率/单位/指标ID/来源），
    第 6 行起为数据行，首列为日期，倒序排列。
    """
    raw = pd.read_excel(C.SAMPLE_XLSX, sheet_name=C.SAMPLE_SHEET)

    # 定位数据起始行：首列为 datetime 实例的第一行
    # （前 5 行是「指标简称/频率/单位/指标ID/来源」等字符串元信息）
    first_col = raw.columns[0]
    is_date = raw[first_col].map(lambda v: isinstance(v, (pd.Timestamp, datetime)))
    if not is_date.any():
        raise ValueError("Excel 首列未找到日期行")
    start = int(np.argmax(is_date.to_numpy()))

    df = raw.iloc[start:].copy()
    df = df.rename(columns={first_col: "date"})
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date"])

    # 指标列重命名
    rename = {k: v for k, v in C.INDICATOR_MAP.items() if k in df.columns}
    missing = set(C.INDICATOR_MAP) - set(rename)
    if missing:
        raise ValueError(f"Excel 缺少预期指标列: {missing}")
    df = df.rename(columns=rename)

    cols = ["date"] + list(C.INDICATOR_MAP.values())
    df = df[cols]
    for c in C.INDICATOR_MAP.values():
        df[c] = pd.to_numeric(df[c], errors="coerce")

    df = df.sort_values("date").reset_index(drop=True)
    return df


# ------------------------------------------------------------------ 黄金价格
def fetch_gold_daily(refresh: bool = False) -> pd.DataFrame:
    """抓取 COMEX 黄金（GC）日线 OHLC，带本地缓存。"""
    if C.GOLD_RAW_CSV.exists() and not refresh:
        df = pd.read_csv(C.GOLD_RAW_CSV, parse_dates=["date"])
        return df.sort_values("date").reset_index(drop=True)

    req = urllib.request.Request(C.SINA_GC_URL, headers=C.REQUEST_HEADERS)
    with urllib.request.urlopen(req, timeout=C.REQUEST_TIMEOUT) as resp:
        text = resp.read().decode("utf-8", errors="ignore")

    m = re.search(r"var\s+_gc\s*=\s*\((.*)\)\s*;?\s*$", text.strip(), re.S)
    if not m:
        raise RuntimeError("新浪黄金日线返回格式异常，无法解析")

    records = json.loads(m.group(1))
    df = pd.DataFrame(records)
    df["date"] = pd.to_datetime(df["date"])
    for c in ("open", "high", "low", "close"):
        df[c] = pd.to_numeric(df[c], errors="coerce")

    df = df[["date", "open", "high", "low", "close"]]
    df = df.dropna(subset=["close"]).sort_values("date").reset_index(drop=True)

    C.GOLD_RAW_CSV.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(C.GOLD_RAW_CSV, index=False)
    return df


# ------------------------------------------------------------------ 合并
def build_dataset(refresh: bool = False, save: bool = True) -> pd.DataFrame:
    """对齐黄金价格与宏观指标，输出建模底表。

    对齐规则：以黄金交易日为基准（目标变量必须有价格），
    宏观指标按日期左连接；宏观指标的非交易日缺失用前值填充（ffill），
    仅向前填充，不使用未来信息。
    """
    gold = fetch_gold_daily(refresh=refresh)
    macro = load_macro_sample()

    df = gold.merge(macro, on="date", how="left")

    # 宏观指标前值填充（VIX/DXY/TIPS 在非交易日为空；GPR/EPU 为自然日序列）
    macro_cols = list(C.INDICATOR_MAP.values())
    df[macro_cols] = df[macro_cols].ffill()

    # 丢弃开头仍有缺失的行（无历史可填充）
    df = df.dropna(subset=macro_cols).reset_index(drop=True)

    if save:
        df.to_csv(C.DATASET_CSV, index=False)
    return df


def describe(df: pd.DataFrame) -> str:
    lines = [
        f"样本区间: {df['date'].min().date()} ~ {df['date'].max().date()}",
        f"样本行数 : {len(df)}",
        f"字段     : {list(df.columns)}",
        "",
        "缺失值统计:",
        df.isna().sum().to_string(),
        "",
        "描述性统计:",
        df.describe().T.to_string(),
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true", help="强制重新抓取黄金价格")
    args = ap.parse_args()

    data = build_dataset(refresh=args.refresh)
    print(describe(data))
    print(f"\n已保存: {C.DATASET_CSV}")
