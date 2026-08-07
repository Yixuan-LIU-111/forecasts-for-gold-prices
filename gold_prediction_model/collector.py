"""采集模块 —— 行情数据采集（重试 / 异常校验 / 定时·触发式拉取）。

数据源：
  - 黄金价格：新浪财经全球期货日 K 线（COMEX 黄金 GC 连续合约），JSONP 接口
  - 宏观指标：docs/data_sample 下 Excel 样本（VIX / GPR / EPU / DXY / TIPS）

设计要点：
  - retry()        ：指数退避 + 抖动 的重试装饰器，覆盖网络/解析/校验异常
  - BaseCollector  ：缓存优先（collect(refresh=False) 读缓存，True 时重拉）
  - SinaGoldCollector / MacroCollector ：具体数据源实现，含数据合法性校验
  - MarketCollector.collect_all() ：返回 (gold_df, macro_df)
  - Scheduler      ：后台线程定时拉取，支持外部触发停止（守护线程，主进程退出即终止）
"""
from __future__ import annotations

import functools
import logging
import random
import re
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Callable
from urllib.request import Request, urlopen

import numpy as np
import pandas as pd

import config as C

log = logging.getLogger("collector")


class CollectionError(RuntimeError):
    """采集相关异常的根类型（网络/解析/校验失败统一抛出）。"""


# ------------------------------------------------------------------ 重试装饰器
def retry(max_attempts: int = 4, base_delay: float = 2.0, max_delay: float = 60.0,
          backoff: float = 2.0, exceptions: tuple = (Exception,), logger=None):
    """指数退避 + 抖动重试。

    用法：
        @retry(max_attempts=4, base_delay=2.0)
        def _fetch_remote(self): ...
    """
    def decorator(fn: Callable):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            _log = logger or log
            last_exc = None
            for attempt in range(1, max_attempts + 1):
                try:
                    return fn(*args, **kwargs)
                except exceptions as exc:  # noqa: BLE001
                    last_exc = exc
                    if attempt >= max_attempts:
                        break
                    delay = min(max_delay, base_delay * (backoff ** (attempt - 1)))
                    delay *= (0.5 + random.random())  # 抖动，避免惊群
                    _log.warning("「%s」第 %d/%d 次失败: %s；%.1fs 后重试",
                                 fn.__name__, attempt, max_attempts, exc, delay)
                    time.sleep(delay)
            raise CollectionError(f"「{fn.__name__}」重试 {max_attempts} 次仍失败: {last_exc}")
        return wrapper
    return decorator


# ------------------------------------------------------------------ 基类
class BaseCollector:
    """缓存优先的数据采集基类。"""

    def __init__(self, cache_path: Path):
        self.cache_path = Path(cache_path)
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)

    def fetch(self, refresh: bool = False) -> pd.DataFrame:
        """触发式拉取：默认读缓存；refresh=True 时重新拉取并落盘。"""
        if not refresh and self.cache_path.exists():
            try:
                df = self._read_cache()
                if self._validate(df):
                    log.info("读取缓存 %s（%d 行）", self.cache_path.name, len(df))
                    return df
                log.warning("缓存 %s 校验未通过，重新拉取", self.cache_path.name)
            except Exception as exc:  # noqa: BLE001
                log.warning("读取缓存失败: %s，重新拉取", exc)
        df = self._fetch_remote()
        self._validate(df)
        self._write_cache(df)
        return df

    # —— 子类需实现 ——
    def _fetch_remote(self) -> pd.DataFrame:
        raise NotImplementedError

    def _read_cache(self) -> pd.DataFrame:
        return pd.read_csv(self.cache_path, parse_dates=["date"])

    def _write_cache(self, df: pd.DataFrame) -> None:
        df.to_csv(self.cache_path, index=False)
        log.info("已缓存 %s（%d 行）", self.cache_path.name, len(df))

    @staticmethod
    def _validate(df: pd.DataFrame) -> bool:
        return df is not None and len(df) > 0


# ------------------------------------------------------------------ 黄金价格
class SinaGoldCollector(BaseCollector):
    """COMEX 黄金日线（新浪 JSONP）。"""

    def __init__(self, url: str = C.SINA_GC_URL, cache_path: Path = C.GOLD_RAW_CSV,
                 headers: dict = None, timeout: int = C.REQUEST_TIMEOUT):
        super().__init__(cache_path)
        self.url = url
        self.headers = headers or C.REQUEST_HEADERS
        self.timeout = timeout

    @retry(max_attempts=4, base_delay=2.0, exceptions=(Exception,))
    def _fetch_remote(self) -> pd.DataFrame:
        req = Request(self.url, headers=self.headers)
        with urlopen(req, timeout=self.timeout) as resp:
            text = resp.read().decode("utf-8", errors="ignore")
        return self._parse(text)

    @staticmethod
    def _parse(text: str) -> pd.DataFrame:
        m = re.search(r"var\s+_gc\s*=\s*\((.*)\)\s*;?\s*$", text.strip(), re.S)
        if not m:
            raise CollectionError("新浪黄金日线返回格式异常，无法解析 JSONP")
        records = _safe_json(m.group(1))
        if not records:
            raise CollectionError("新浪黄金日线返回为空")
        df = pd.DataFrame(records)
        df["date"] = pd.to_datetime(df["date"])
        for c in ("open", "high", "low", "close"):
            df[c] = pd.to_numeric(df[c], errors="coerce")
        df = df[["date", "open", "high", "low", "close"]].dropna(subset=["close"])
        df = df.sort_values("date").reset_index(drop=True)
        return df

    @staticmethod
    def _validate(df: pd.DataFrame) -> bool:
        if df is None or len(df) < 50:
            raise CollectionError(f"黄金数据行数异常: {None if df is None else len(df)}")
        if df["close"].isna().all():
            raise CollectionError("黄金 close 全为空")
        # 日期应严格递增（允许同日重复时去重）
        if not df["date"].is_monotonic_increasing:
            raise CollectionError("黄金数据日期非递增")
        # 单日涨跌幅不应出现 >50% 的明显脏值
        ret = df["close"].pct_change()
        if ret.abs().max() > 0.5:
            raise CollectionError(f"黄金日收益存在异常跳变: {ret.abs().max():.2%}")
        return True


# ------------------------------------------------------------------ 宏观指标
class MacroCollector(BaseCollector):
    """宏观指标（Excel 样本，本地文件；预留远程拉取接口）。"""

    def __init__(self, xlsx: Path = C.SAMPLE_XLSX, sheet: str = C.SAMPLE_SHEET,
                 cache_path: Path = None):
        cache = cache_path or (C.DATA_DIR / "macro_sample_cache.csv")
        super().__init__(cache)
        self.xlsx = Path(xlsx)
        self.sheet = sheet

    @retry(max_attempts=3, base_delay=1.0, exceptions=(Exception,))
    def _fetch_remote(self) -> pd.DataFrame:
        if not self.xlsx.exists():
            raise CollectionError(f"宏观样本文件不存在: {self.xlsx}")
        raw = pd.read_excel(self.xlsx, sheet_name=self.sheet)
        return self._parse(raw)

    @staticmethod
    def _parse(raw: pd.DataFrame) -> pd.DataFrame:
        first_col = raw.columns[0]
        is_date = raw[first_col].map(
            lambda v: isinstance(v, (pd.Timestamp, datetime)))
        if not is_date.any():
            raise CollectionError("Excel 首列未找到日期行")
        start = int(np.argmax(is_date.to_numpy()))
        df = raw.iloc[start:].copy().rename(columns={first_col: "date"})
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        df = df.dropna(subset=["date"])
        rename = {k: v for k, v in C.INDICATOR_MAP.items() if k in df.columns}
        if not rename:
            raise CollectionError("Excel 缺少预期宏观指标列")
        df = df.rename(columns=rename)
        df = df[["date"] + list(C.INDICATOR_MAP.values())]
        for c in C.INDICATOR_MAP.values():
            df[c] = pd.to_numeric(df[c], errors="coerce")
        return df.sort_values("date").reset_index(drop=True)

    @staticmethod
    def _validate(df: pd.DataFrame) -> bool:
        if df is None or len(df) < 100:
            raise CollectionError(f"宏观数据行数异常: {None if df is None else len(df)}")
        if df[list(C.INDICATOR_MAP.values())].isna().all().all():
            raise CollectionError("宏观指标全为空")
        return True

    # 远程拉取接入位：未来可在此实现 HTTP 下载后走 _parse
    def fetch_remote_source(self, url: str, token: str | None = None):
        raise NotImplementedError("远程宏观数据源接入位（当前使用本地 Excel 样本）")


# ------------------------------------------------------------------ 组合采集
class MarketCollector:
    """行情总入口：同时采集黄金价格与宏观指标。"""

    def __init__(self, gold: BaseCollector = None, macro: BaseCollector = None):
        self.gold = gold or SinaGoldCollector()
        self.macro = macro or MacroCollector()

    def collect_all(self, refresh_gold: bool = False,
                    refresh_macro: bool = False) -> tuple[pd.DataFrame, pd.DataFrame]:
        """触发式采集，返回 (gold_df, macro_df)。"""
        log.info("▶ 开始采集行情数据 …")
        gold = self.gold.fetch(refresh=refresh_gold)
        macro = self.macro.fetch(refresh=refresh_macro)
        log.info("✓ 采集完成：黄金 %d 行，宏观 %d 行",
                 len(gold), len(macro))
        return gold, macro


# ------------------------------------------------------------------ 定时调度
class Scheduler:
    """后台线程定时拉取（守护线程）。支持 trigger 式 start/stop。"""

    def __init__(self, task: Callable[[], None], interval_sec: float = 86400,
                 logger=None):
        self.task = task
        self.interval = interval_sec
        self._stop = threading.Event()
        self._thread = None
        self._log = logger or log

    def _loop(self):
        self._log.info("调度器启动：每 %.0f 秒拉取一次", self.interval)
        while not self._stop.is_set():
            try:
                self.task()
            except Exception as exc:  # noqa: BLE001
                self._log.error("调度任务执行异常: %s", exc)
            self._stop.wait(self.interval)

    def start(self):
        if self._thread and self._thread.is_alive():
            self._log.warning("调度器已在运行")
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        self._log.info("调度器已停止")


def _safe_json(s: str):
    import json
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        # 容错：去掉可能的尾随逗号 / BOM
        return json.loads(s.strip().strip("\ufeff"))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    g, m = MarketCollector().collect_all(refresh_gold=False, refresh_macro=False)
    print(g.tail())
    print(m.tail())
