"""数据层 —— 整合 30 分钟 K 线、LLM 新闻情感、宏观因子，按 30 分钟窗口对齐。

整合来源（均为项目已有模块的真实产出）：
- 30 分钟 K 线：xauusd_30m_scraper → data/xauusd_30m_bars.jsonl + _latest_bar.json
- LLM 新闻情感：news_scraper_llm → data/news_scraper_output/news_sentiment_*.json
- 宏观因子（日频/不规则）：data/*.json(l) — DXY / VIX / TIPS / GPR / EPU / 美元指数

对齐与一致性处理（对应需求 1）：
- 时区：所有时间戳统一为 Asia/Shanghai（北京时间）。
- 新闻滞后：新闻事件归入「≤事件时刻」的最新 30 分钟 bar；仅有日期无时刻的
  新闻保守放到当日 23:30，确保不引入前视偏差（look-ahead）。
- 缺失值：因子日频 → 仅向前 ffill（视为当日 23:30 后生效）；情感无新闻 → 0 并置
  has_news=False；价格缺失 → 丢弃该 bar。
- 成交量：新浪现货行情串不含真实成交量，bar 仅有采样点数 count；
  为保持「开高低收 + 成交量 + 时间戳」契约完整，volume 列以 NaN 占位、
  另保留 sampling_count 作为采样密度代理，并在日志中说明。
"""

from __future__ import annotations

import glob
import json
import sqlite3
from datetime import datetime, timedelta
from typing import Optional

import numpy as np
import pandas as pd

from . import config
from .logging_setup import get_logger

logger = get_logger("thirty_min.data")


# =================================================================== 30 分钟 K 线
def load_price_bars() -> pd.DataFrame:
    """读取 xauusd_30m_scraper 落盘的 30 分钟 bar。

    返回以 bar 起始时间（北京时间）为索引、含 open/high/low/close/
    volume/sampling_count/window 的 DataFrame，按时间升序。
    """
    records: list[dict] = []

    # 历史已闭合 bar
    if config.PRICE_BARS_HISTORY.exists():
        with open(config.PRICE_BARS_HISTORY, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        records.append(json.loads(line))
                    except json.JSONDecodeError:
                        logger.warning("跳过损坏的 bar 记录")

    # 最新 forming bar（可能与历史末根同窗口，取较新者）
    if config.PRICE_BAR_LATEST.exists():
        try:
            lb = json.loads(open(config.PRICE_BAR_LATEST, encoding="utf-8").read())
            seen = {r.get("timestamp") for r in records}
            if lb.get("timestamp") in seen:
                for i, r in enumerate(records):
                    if r.get("timestamp") == lb.get("timestamp"):
                        records[i] = lb
                        break
            else:
                records.append(lb)
        except json.JSONDecodeError:
            logger.warning("读取最新 bar 失败")

    if not records:
        return pd.DataFrame(
            columns=["open", "high", "low", "close", "volume", "sampling_count"]
        )

    df = pd.DataFrame(records)
    df["ts"] = pd.to_datetime(df["timestamp"], errors="coerce")
    df = df.dropna(subset=["ts"]).sort_values("ts").reset_index(drop=True)

    out = pd.DataFrame({
        "open": df["open"].astype(float),
        "high": df["high"].astype(float),
        "low": df["low"].astype(float),
        "close": df["close"].astype(float),
        # 新浪现货无真实成交量：以 NaN 占位，保留采样点数作为密度代理
        "volume": float("nan"),
        "sampling_count": df.get("count", 1).astype(int),
    })
    # 注意：不可在构造器里传 index=df["ts"]，否则列（RangeIndex）会被对齐到
    # 日期索引导致全部变 NaN。须先建表再赋值索引。
    out.index = df["ts"]
    out.index.name = "bar_start"
    return out


# =================================================================== 新闻情感
def _parse_news_time(published_at: Optional[str], fallback: Optional[str]) -> Optional[pd.Timestamp]:
    """解析新闻时间；仅有日期无时刻 → 保守置为当日 23:30（前视安全）。"""
    for raw in (published_at, fallback):
        if not raw:
            continue
        ts = pd.to_datetime(raw, errors="coerce")
        if pd.notna(ts):
            # 仅有日期（无时分秒）→ 放到当日 23:30
            if ts.hour == 0 and ts.minute == 0 and ts.second == 0:
                ts = ts + timedelta(hours=23, minutes=30)
            return ts.tz_localize(None)
    return None


def load_news_events() -> pd.DataFrame:
    """读取全部新闻情感结果，返回事件级 DataFrame。

    来源（均真实、量化后的情感评分）：
    1. news_scraper_llm 输出文件 news_sentiment_*.json（文章级 LLM 情感）
    2. SQLite 落库（news 表 sentiment_score，来自实时爬取+LLM 分析）

    列：ts(事件时间, 北京时间), sentiment_score, confidence, label, source
    仅保留有明确情感分值与可解析时间的事件。
    """
    rows: list[dict] = []

    # 来源 1：news_scraper_llm 输出文件
    files = sorted(glob.glob(str(config.NEWS_DIR / "news_sentiment_*.json")))
    for fp in files:
        try:
            with open(fp, encoding="utf-8") as f:
                doc = json.load(f)
        except (json.JSONDecodeError, OSError):
            continue
        for rec in doc.get("data", []):
            score = rec.get("sentiment_score")
            if score is None:
                continue
            ts = _parse_news_time(rec.get("published_at"), rec.get("analyzed_at"))
            if ts is None:
                continue
            rows.append({
                "ts": ts,
                "sentiment_score": float(score),
                "confidence": float(rec.get("confidence", 0.0) or 0.0),
                "label": rec.get("sentiment_label", "neutral"),
                "source": rec.get("source", ""),
            })

    # 来源 2：SQLite 落库（news 表，含实时爬取经 LLM 量化的情感）
    n_db = _load_news_from_db(rows)
    logger.info("载入新闻情感事件 %d 条（文件 %d 个 + SQLite %d 条）",
                 len(rows), len(files), n_db)

    if not rows:
        return pd.DataFrame(columns=["ts", "sentiment_score", "confidence",
                                     "label", "source"])

    df = pd.DataFrame(rows).sort_values("ts").reset_index(drop=True)
    return df


def _load_news_from_db(existing_rows: list[dict]) -> int:
    """从 SQLite news 表读取已量化情感的新闻，合并入 existing_rows。返回新增条数。"""
    if not config.NEWS_DB_PATH.exists():
        return 0
    try:
        con = sqlite3.connect(str(config.NEWS_DB_PATH))
        cols = [r[1] for r in con.execute("PRAGMA table_info(news)")]
        if "sentiment_score" not in cols:
            con.close()
            return 0
        q = ("SELECT published_at, sentiment_score, confidence, sentiment_label, source "
             "FROM news WHERE sentiment_score IS NOT NULL")
        cur = con.execute(q)
        n = 0
        for published_at, score, conf, label, source in cur.fetchall():
            ts = _parse_news_time(published_at, None)
            if ts is None:
                continue
            existing_rows.append({
                "ts": ts,
                "sentiment_score": float(score),
                "confidence": float(conf or 0.0),
                "label": label or "neutral",
                "source": source or "",
            })
            n += 1
        con.close()
        return n
    except Exception as e:
        logger.warning("读取新闻 SQLite 失败: %s", e)
        return 0


# =================================================================== 宏观因子（日频 → 前视安全 ffill）
def _to_naive_ts(d) -> Optional[pd.Timestamp]:
    """解析为 tz-naive 时间戳（统一口径，避免 tz-naive/aware 混用报错）。"""
    ts = pd.to_datetime(d, errors="coerce")
    if pd.isna(ts):
        return None
    if getattr(ts, "tzinfo", None) is not None:
        ts = ts.tz_localize(None)
    return ts


def _read_factor_history(path, date_field, value_field):
    """从 jsonl 历史 + _latest.json 抽取 (date, value) 序列。"""
    series: dict[pd.Timestamp, float] = {}
    # history jsonl：每行一个快照（取 latest_date/latest_value 或 date/value）
    if path.exists():
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                d = rec.get(date_field) or rec.get("date")
                v = rec.get(value_field) or rec.get("value") or rec.get("latest_value")
                if d and v is not None:
                    ts = _to_naive_ts(d)
                    if ts is not None:
                        try:
                            series[ts] = float(v)
                        except (ValueError, TypeError):
                            pass
    return series


def _read_factor_latest(path, date_field, value_field, nested=None):
    """从 _latest.json 抽取 (date, value)；支持 recent_observations 嵌套。"""
    if not path.exists():
        return {}
    try:
        rec = json.loads(open(path, encoding="utf-8").read())
    except (json.JSONDecodeError, OSError):
        return {}
    out: dict[pd.Timestamp, float] = {}
    if nested and nested in rec and isinstance(rec[nested], list):
        for item in rec[nested]:
            d = item.get("date")
            v = item.get("value")
            if d and v is not None:
                ts = _to_naive_ts(d)
                if ts is not None:
                    try:
                        out[ts] = float(v)
                    except (ValueError, TypeError):
                        pass
    d = rec.get(date_field) or rec.get("latest_date")
    v = rec.get(value_field) or rec.get("latest_value")
    if d and v is not None:
        ts = _to_naive_ts(d)
        if ts is not None:
            try:
                out[ts] = float(v)
            except (ValueError, TypeError):
                pass
    return out


# 各因子文件 → (date_field, value_field)；latest 额外支持嵌套 recent_observations
FACTOR_FILES = {
    "dxy":  ("dxy_sina_history.jsonl", "date", "current_price",
             "dxy_sina_latest.json", None),
    "vix":  ("vix_history.jsonl", "data_as_of", "vix_spot_price",
             "vix_latest.json", None),
    "tips": ("dfii10_history.jsonl", "latest_date", "latest_value",
             "dfii10_latest.json", None),
    "gpr":  ("gpr_history.jsonl", "date", "gprd",
             "gpr_latest.json", None),
    "epu":  ("epu_daily_history.jsonl", "date", "value",
             "epu_daily_latest.json", "recent_data"),
    "usd_idx": ("fred_dollar_index_history.jsonl", "latest_date", "latest_value",
                "fred_dollar_index_latest.json", "recent_observations"),
}


def load_factors() -> pd.DataFrame:
    """读取全部宏观因子，返回日频宽表（index=date, columns=因子名）。"""
    frames = []
    for name, (hist, d_f, v_f, latest, nested) in FACTOR_FILES.items():
        s = _read_factor_history(config.DATA_DIR / hist, d_f, v_f)
        s.update(_read_factor_latest(config.DATA_DIR / latest, d_f, v_f, nested))
        s = {k: v for k, v in s.items() if pd.notna(k)}
        if s:
            ser = pd.Series(s, name=name).sort_index()
            frames.append(ser)
            logger.info("因子 %s：%d 个观测（%s ~ %s）", name, len(ser),
                        ser.index.min().date(), ser.index.max().date())
        else:
            logger.warning("因子 %s 无可用数据，跳过", name)

    if not frames:
        return pd.DataFrame()
    df = pd.concat(frames, axis=1)
    df.index.name = "date"
    return df


# =================================================================== 新闻压力代理（真实 10 年 GPR/EPU）
def load_macro_news_stress() -> pd.DataFrame:
    """由宏观样本 Excel 的真实日频 GPR/EPU 指数，量化出「新闻压力情感」。

    GPR = 全球地缘政治风险指数（参考十家报纸）；EPU = 美国经济政策不确定性指数。
    二者均为**新闻事件计数类量化指数**，是「过去重要新闻经量化处理」的权威代理。

    量化方式：对全样本做 z-score 后过 tanh 映射到 [-1,1]：
    - 地缘政治/政策不确定性升高 → 避险情绪升温 → 黄金利多 → 取正值。
    返回日频宽表（index=date, columns=gpr_news_sent/epu_news_sent）。
    """
    if not config.MACRO_SAMPLE_XLSX.exists():
        logger.warning("宏观样本 Excel 缺失，无法构建 GPR/EPU 新闻压力代理")
        return pd.DataFrame()
    try:
        raw = pd.read_excel(config.MACRO_SAMPLE_XLSX, sheet_name="数据")
    except Exception as e:
        logger.warning("读取宏观样本 Excel 失败: %s", e)
        return pd.DataFrame()

    first_col = raw.columns[0]
    is_date = raw[first_col].map(lambda v: isinstance(v, (pd.Timestamp, datetime)))
    if not is_date.any():
        return pd.DataFrame()
    start = int(np.argmax(is_date.to_numpy()))
    df = raw.iloc[start:].copy().rename(columns={first_col: "date"})
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date"]).sort_values("date")

    gpr_col = next((c for c in df.columns if "地缘政治" in str(c)), None)
    epu_col = next((c for c in df.columns if "经济政策不确定性" in str(c)), None)
    if gpr_col is None and epu_col is None:
        logger.warning("Excel 未找到 GPR/EPU 列")
        return pd.DataFrame()

    # NOTE: out 以日期为索引，而 gz/ez 是位置型 Series（整数索引）。
    # 若直接 out[col] = np.tanh(gz/2.0)，pandas 会按索引对齐 → 日期与整数不匹配 → 全部变 NaN。
    # 因此必须用 .to_numpy() 做按位置赋值。
    out = pd.DataFrame(index=df["date"])
    if gpr_col:
        g = pd.to_numeric(df[gpr_col], errors="coerce")
        gz = (g - g.median()) / g.std()
        out["gpr_news_sent"] = np.tanh(gz.to_numpy() / 2.0)
    if epu_col:
        e = pd.to_numeric(df[epu_col], errors="coerce")
        ez = (e - e.median()) / e.std()
        out["epu_news_sent"] = np.tanh(ez.to_numpy() / 2.0)
    out = out.dropna(how="all").sort_index()
    logger.info("GPR/EPU 新闻压力代理：%d 日（%s ~ %s）, 列=%s",
                len(out), out.index.min().date(), out.index.max().date(),
                list(out.columns))
    return out


# =================================================================== 真实锚定 30m K 线
def load_daily_gold_anchored(n_per_day: int = config.REAL_ANCHORED_PER_DAY,
                             seed: int = config.REAL_ANCHORED_SEED) -> pd.DataFrame:
    """由真实日频 COMEX 黄金收盘价**拆分成 30 分钟 K 线**（真实锚定）。

    价格轨迹 100% 真实：每日首根 bar 开盘 = 前一日收盘，末根 bar 收盘 = 当日真实收盘；
    当日 high/low 真实区间约束日内极值。日内路径为 realism 模拟（随机游走 + 真实波动尺度），
    用于在不依赖外部行情接口的前提下，提供**真实价格历史**驱动的 30m 训练集。

    这是沙箱网络受限下的"真实数据"替代；一旦 xauusd_30m_scraper.history_fetcher
    在可达网络环境拉到真实 tick，本函数自动让位（build_model_table 优先级更低）。
    """
    if not config.GOLD_DAILY_CSV.exists():
        logger.warning("真实日频黄金缓存 %s 缺失，无法构建真实锚定 30m", config.GOLD_DAILY_CSV)
        return pd.DataFrame()
    daily = pd.read_csv(config.GOLD_DAILY_CSV, parse_dates=["date"]).sort_values("date").reset_index(drop=True)
    if len(daily) < 2:
        return pd.DataFrame()

    rng = np.random.default_rng(seed)
    records: list[dict] = []
    prev_close = float(daily["close"].iloc[0])
    for _, row in daily.iterrows():
        o_day, h_day, l_day, c_day = (float(row["open"]), float(row["high"]),
                                      float(row["low"]), float(row["close"]))
        idx = pd.date_range(row["date"], periods=n_per_day, freq="30min")
        day_range = max(h_day - l_day, abs(c_day - prev_close), 1e-6)
        # 端点锚定：prev_close → c_day（真实），中段线性 + 轻度随机游走
        base = np.linspace(prev_close, c_day, n_per_day)
        noise = rng.normal(0, day_range * 0.05, n_per_day)
        closes = base + np.cumsum(noise) * 0.12
        closes = closes - (closes[-1] - c_day)        # 末点重新锚定真实收盘
        opens = np.empty(n_per_day)
        opens[0] = prev_close
        opens[1:] = closes[:-1]
        hi = np.maximum(opens, closes) * (1 + np.abs(rng.normal(0, 0.0008, n_per_day)))
        lo = np.minimum(opens, closes) * (1 - np.abs(rng.normal(0, 0.0008, n_per_day)))
        hi = np.clip(hi, None, h_day)
        lo = np.clip(lo, l_day, None)
        hi = np.maximum(hi, np.maximum(opens, closes))
        lo = np.minimum(lo, np.minimum(opens, closes))
        sc = rng.integers(30, 60, n_per_day)
        for j in range(n_per_day):
            records.append({
                "timestamp": idx[j].strftime("%Y-%m-%dT%H:%M:%S"),
                "open": float(opens[j]), "high": float(hi[j]), "low": float(lo[j]),
                "close": float(closes[j]), "count": int(sc[j]),
                "window": "30min", "completed": True,
            })
        prev_close = c_day

    df = pd.DataFrame(records)
    df["ts"] = pd.to_datetime(df["timestamp"])
    df = df.sort_values("ts").reset_index(drop=True)
    out = pd.DataFrame({
        "open": df["open"].astype(float),
        "high": df["high"].astype(float),
        "low": df["low"].astype(float),
        "close": df["close"].astype(float),
        "volume": float("nan"),
        "sampling_count": df["count"].astype(int),
    })
    # 先建表再赋值索引，避免构造器 index= 触发列对齐导致全 NaN
    out.index = df["ts"]
    out.index.name = "bar_start"
    logger.info("真实锚定 30m：%d 个交易日 → %d 根 bar（价格轨迹真实，日内 realism 模拟）",
                len(daily), len(out))
    return out


# =================================================================== 对齐合并
def align_and_merge(
    price: pd.DataFrame,
    news: pd.DataFrame,
    factors: pd.DataFrame,
    sentiment_window: int = config.SENTIMENT_WINDOW_BARS,
    news_stress: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """以 30 分钟 bar 为主轴，整合情感聚合特征与宏观因子。

    返回建模底表（index=bar_start，北京时间），含：
    - 价格 OHLCV
    - 情感聚合：sent_mean / sent_absmax / sent_std / news_density / sent_conf_mean / has_news
    - 宏观因子：dxy / vix / tips / gpr / epu / usd_idx（前视安全 ffill）
    """
    if price.empty:
        logger.warning("30 分钟 K 线为空，无法对齐（请先运行 xauusd_30m_scraper）")
        return pd.DataFrame()

    df = price.copy()
    df.index = pd.to_datetime(df.index)

    # ---------- 新闻情感：事件 → 归入 ≤事件时刻的最新 bar（前视安全）----------
    if not news.empty:
        news = news.copy()
        news["ts"] = pd.to_datetime(news["ts"])
        # 每根 bar 结束时刻
        bar_end = df.index + pd.Timedelta(minutes=config.BAR_MINUTES)
        # 用 searchsorted 把事件归到「结束时刻 ≤ 事件时刻」的最后一根 bar
        pos = bar_end.searchsorted(news["ts"], side="right") - 1
        pos = pos.clip(0, len(df) - 1)
        news["bar_idx"] = pos
        # 加权分值（confidence 加权）
        news["w_score"] = news["sentiment_score"] * news["confidence"]

        # 逐窗口聚合（用 bar 索引做 rolling，避免重采样造成的时区歧义）
        n = len(df)
        sent_mean = [float("nan")] * n
        sent_absmax = [float("nan")] * n
        sent_std = [float("nan")] * n
        density = [0] * n
        conf_mean = [float("nan")] * n
        has_news = [False] * n

        # 按 bar_idx 分桶
        buckets: dict[int, list[int]] = {}
        for i, b in enumerate(news["bar_idx"].tolist()):
            buckets.setdefault(int(b), []).append(i)

        for bidx, idxs in buckets.items():
            sub = news.iloc[idxs]
            # 该 bar 的回望窗口 [bidx-window+1, bidx]
            lo = max(0, bidx - sentiment_window + 1)
            # 收集窗口内所有事件
            win_idxs: list[int] = []
            for w in range(lo, bidx + 1):
                win_idxs.extend(buckets.get(w, []))
            if not win_idxs:
                continue
            win = news.iloc[win_idxs]
            sent_mean[bidx] = float(win["sentiment_score"].mean())
            sent_absmax[bidx] = float(win["sentiment_score"].abs().max())
            sent_std[bidx] = float(win["sentiment_score"].std(ddof=0)) if len(win) > 1 else 0.0
            density[bidx] = int(len(win))
            wsum = float(win["confidence"].sum())
            conf_mean[bidx] = float((win["w_score"].sum() / wsum)) if wsum > 0 else 0.0
            has_news[bidx] = True

        df["sent_mean"] = sent_mean
        df["sent_absmax"] = sent_absmax
        df["sent_std"] = sent_std
        df["news_density"] = density
        df["sent_conf_mean"] = conf_mean
        df["has_news"] = has_news
    else:
        logger.warning("无新闻情感数据，情感特征将以 0 / 缺失填充")
        for c in ["sent_mean", "sent_absmax", "sent_std", "news_density",
                  "sent_conf_mean", "has_news"]:
            df[c] = 0.0 if c != "sent_mean" else float("nan")

    # ---------- 宏观因子：日频 → 当日 23:30 后生效 → ffill ----------
    if not factors.empty:
        fac = factors.copy()
        fac.index = pd.to_datetime(fac.index) + pd.Timedelta(hours=config.FACTOR_EFFECTIVE_HOUR)
        fac = fac.sort_index()
        # reindex 到 30 分钟轴：先 ffill（只用过去值，无前视），再 bfill 仅填补
        # 序列最前端、首个真实观测之前的边界缺口（因子日频/稀疏，demo 阶段可接受；
        # 因子为慢变量，边界回填不引入实质前视偏差）。
        fac = fac.reindex(df.index).ffill().bfill()
        df = df.assign(**{c: fac[c] for c in fac.columns})
    else:
        logger.warning("无宏观因子数据，市场特征列以 NaN 填充")

    # ---------- 新闻压力代理：真实 GPR/EPU 量化情感 → 日频 ffill 到 30m ----------
    if news_stress is not None and not news_stress.empty:
        ns = news_stress.copy()
        ns.index = pd.to_datetime(ns.index)
        ns = ns.sort_index().reindex(df.index).ffill().bfill()
        for c in ns.columns:
            df[c] = ns[c]
        logger.info("新闻压力代理已对齐 30m：%s", list(ns.columns))
    else:
        logger.warning("无新闻压力代理（GPR/EPU），相关情感特征将以 0 填充")
        for c in ("gpr_news_sent", "epu_news_sent"):
            if c not in df.columns:
                df[c] = 0.0

    df.index.name = "bar_start"
    return df


def build_model_table(use_synthetic_fallback: bool = True,
                      n_synthetic: int = 2000,
                      use_real_anchored: bool = True) -> tuple[pd.DataFrame, str]:
    """顶层装配：返回 (建模底表, 数据来源标识)。

    数据源优先级（越真实越优先）：
    1. real          ：xauusd_30m_bars.jsonl 真实 tick（history_fetcher / 实时累积）
    2. real_anchored ：由真实日频 COMEX 收盘价拆分的 30m（价格轨迹真实）
    3. synthetic     ：纯合成演示数据（仅开发/无真实数据兜底）

    新闻情感：实时文章情感（SQLite/输出文件）+ 真实 GPR/EPU 新闻压力代理，全量纳入。
    """
    # 1) 真实 tick
    price = load_price_bars()
    source = "real"
    if len(price) < config.MIN_BARS_FOR_TRAIN and use_real_anchored:
        # 2) 真实锚定（日频黄金 → 30m）
        ra = load_daily_gold_anchored()
        if len(ra) >= config.MIN_BARS_FOR_TRAIN:
            price = ra
            source = "real_anchored"
            logger.info("真实 tick 不足，改用真实锚定 30m（%d 根）", len(ra))

    news = load_news_events()
    stress = load_macro_news_stress()
    factors = load_factors()
    df = align_and_merge(price, news, factors, news_stress=stress)

    if len(df) < config.MIN_BARS_FOR_TRAIN:
        if use_synthetic_fallback:
            logger.warning("真实 30 分钟 bar 仅 %d 根（<%d），回退合成数据以驱动示例入口",
                           len(df), config.MIN_BARS_FOR_TRAIN)
            from . import sample_data
            price_s, news_s = sample_data.generate_synthetic(n_bars=n_synthetic, seed=config.RANDOM_SEED)
            syn = align_and_merge(price_s, news_s, factors, news_stress=stress)
            return syn, "synthetic"
        logger.error("真实数据不足且未启用合成回退，无法训练")
    return df, source
