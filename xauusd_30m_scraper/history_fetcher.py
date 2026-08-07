"""真实 30 分钟历史 K 线抓取器（XAU/USD）。

数据来源（按优先级尝试，全部带指数退避重试）：
1. Yahoo Finance 图表 API（GC=F，COMEX 黄金期货，30m 粒度，UTC epoch）
2. stooq（xauusd，i=30 分钟，CSV）

落盘：与实时聚合器**完全相同的 schema** → data/xauusd_30m_bars.jsonl
（字段：timestamp/open/high/low/close/count/window/completed），
确保 thirty_min 数据层 load_price_bars() 无需改动即可消费真实历史。

设计要点：
- 网络受限环境（如本沙箱）下，Yahoo/stooq 可能返回 403/JS 挑战/超时；
  本模块会**优雅降级**并打印明确提示，绝不伪造数据。
- 时间戳统一转为北京时间（Asia/Shanghai）ISO 字符串，与实时 bar 一致。
- 校验：非空、时间戳单调递增、OHLC 自洽（high≥max, low≤min）、去重。

用法（仓库根目录）：
    python -m xauusd_30m_scraper.history_fetcher --years 2
    python -m xauusd_30m_scraper.history_fetcher --start 2024-01-01 --end 2026-08-01
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timedelta, timezone

import requests

from . import config

BEIJING = timezone(timedelta(hours=8))
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")


def _beijing_iso(epoch_sec: float) -> str:
    """UTC epoch 秒 → 北京时间 ISO（无时区后缀，与实时 bar 一致）。"""
    dt = datetime.fromtimestamp(epoch_sec, tz=timezone.utc).astimezone(BEIJING)
    return dt.strftime("%Y-%m-%dT%H:%M:%S")


def _http_get(url: str, params: dict | None, headers: dict, tries: int = 4) -> requests.Response | None:
    for i in range(tries):
        try:
            r = requests.get(url, params=params, headers=headers, timeout=20)
            if r.status_code == 200:
                return r
            if r.status_code == 429:
                wait = min(2 ** (i + 1) * 1.5, 30) + i * 0.3
                time.sleep(wait)
                continue
            # 4xx 一般无需重试
            return r
        except Exception as e:
            time.sleep(min(2 ** i, 10))
    return None


# ------------------------------------------------------------------ Yahoo
def fetch_yahoo(start: datetime, end: datetime, chunk_days: int = 4) -> list[dict]:
    """按 chunk_days 分块拉取 Yahoo 30m 历史，返回 bar 记录列表。"""
    bars: list[dict] = []
    cursor = start
    while cursor < end:
        chunk_end = min(cursor + timedelta(days=chunk_days), end)
        p1 = int(cursor.timestamp())
        p2 = int(chunk_end.timestamp())
        url = "https://query1.finance.yahoo.com/v8/finance/chart/GC=F"
        r = _http_get(url, {"period1": p1, "period2": p2, "interval": "30m"},
                      {"User-Agent": UA, "Accept": "application/json"})
        if r is None or r.status_code != 200:
            raise RuntimeError(f"Yahoo 拉取失败 status={r.status_code if r else 'timeout'}")
        j = r.json()
        res = (j.get("chart") or {}).get("result")
        if not res:
            cursor = chunk_end
            continue
        ts = res[0]["timestamp"]
        q = res[0]["indicators"]["quote"][0]
        for i, t in enumerate(ts):
            o = q["open"][i]; h = q["high"][i]; l = q["low"][i]; c = q["close"][i]
            if None in (o, h, l, c):
                continue
            bars.append({
                "timestamp": _beijing_iso(t),
                "open": float(o), "high": float(h),
                "low": float(l), "close": float(c),
                "count": 1, "window": "30min", "completed": True,
            })
        cursor = chunk_end + timedelta(minutes=1)
        time.sleep(0.4)
    return bars


# ------------------------------------------------------------------ stooq
def fetch_stooq(start: datetime, end: datetime) -> list[dict]:
    """stooq 30m CSV（i=30）。注意：stooq 免费接口常有反爬 JS 挑战，失败即抛错。"""
    url = "https://stooq.com/q/d/l/"
    r = _http_get(url, {"s": "xauusd", "i": "30",
                        "d1": start.strftime("%Y%m%d"),
                        "d2": end.strftime("%Y%m%d")},
                  {"User-Agent": UA})
    if r is None or r.status_code != 200 or "<html" in r.text[:200].lower():
        raise RuntimeError("stooq 返回非 CSV（可能被反爬拦截）")
    bars: list[dict] = []
    for line in r.text.strip().splitlines()[1:]:
        parts = line.split(",")
        if len(parts) < 5:
            continue
        try:
            d, o, h, l, c = parts[0], float(parts[1]), float(parts[2]), float(parts[3]), float(parts[4])
            ts = datetime.strptime(d, "%Y-%m-%d %H:%M:%S").strftime("%Y-%m-%dT%H:%M:%S")
            bars.append({"timestamp": ts, "open": o, "high": h, "low": l,
                         "close": c, "count": 1, "window": "30min", "completed": True})
        except ValueError:
            continue
    return bars


# ------------------------------------------------------------------ 校验 + 落盘
def _validate(bars: list[dict]) -> list[dict]:
    seen = set()
    out = []
    last_ts = None
    for b in sorted(bars, key=lambda x: x["timestamp"]):
        if b["timestamp"] in seen:
            continue
        try:
            o, h, l, c = b["open"], b["high"], b["low"], b["close"]
        except KeyError:
            continue
        if not (h >= max(o, c) - 1e-9 and l <= min(o, c) + 1e-9 and c > 0):
            continue
        if last_ts is not None and b["timestamp"] <= last_ts:
            continue
        seen.add(b["timestamp"])
        last_ts = b["timestamp"]
        out.append(b)
    return out


def run(start: datetime, end: datetime, source_pref: tuple = ("yahoo", "stooq")) -> dict:
    """抓取并落盘真实 30m 历史；返回状态摘要。"""
    errors = []
    bars: list[dict] = []
    for src in source_pref:
        try:
            if src == "yahoo":
                bars = fetch_yahoo(start, end)
            elif src == "stooq":
                bars = fetch_stooq(start, end)
            if bars:
                break
        except Exception as e:
            errors.append(f"{src}: {type(e).__name__}: {str(e)[:160]}")
            continue

    if not bars:
        return {"ok": False, "bars": 0,
                "errors": errors,
                "message": "所有真实数据源均不可用（多为沙箱网络受限）。"
                           "请在网络可达环境运行本模块以获取真实 30m 历史；"
                           "或先用 Sina 实时报价累积真实 bar。"}

    bars = _validate(bars)
    out_path = config.BARS_HISTORY_FILE
    with open(out_path, "w", encoding="utf-8") as f:
        for b in bars:
            f.write(json.dumps(b, ensure_ascii=False) + "\n")
    return {"ok": True, "bars": len(bars), "file": str(out_path), "errors": errors,
            "message": f"已写入 {len(bars)} 根真实 30m bar"}


def main():
    ap = argparse.ArgumentParser(description="抓取真实 XAU/USD 30m 历史 K 线")
    ap.add_argument("--years", type=float, default=2, help="回看年数（默认 2 年）")
    ap.add_argument("--start", type=str, default=None, help="起始日期 YYYY-MM-DD")
    ap.add_argument("--end", type=str, default=None, help="结束日期 YYYY-MM-DD")
    args = ap.parse_args()

    end = datetime.strptime(args.end, "%Y-%m-%d") if args.end else datetime(2026, 8, 6)
    start = (datetime.strptime(args.start, "%Y-%m-%d") if args.start
             else end - timedelta(days=int(args.years * 365)))
    res = run(start, end)
    print(json.dumps(res, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
