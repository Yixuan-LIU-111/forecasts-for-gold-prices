"""具体采集器适配器：封装项目根目录的独立爬虫模块。

各爬虫使用相对导入（from config import ...），需先把其目录加入 sys.path。
Playwright 依赖（dxy/vix）可能未安装，采集失败时优雅降级。
"""
from __future__ import annotations

import importlib
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from app.config import PROJECT_ROOT, settings
from app.core.collectors.base import CollectorResult, DataCollector

logger = logging.getLogger(__name__)

_SCRAPER_DIR = PROJECT_ROOT  # 爬虫模块位于项目根目录


def _load_scraper_module(scraper_dir: str, module_name: str = "scraper"):
    """动态加载爬虫模块（处理相对导入）。

    返回模块对象，或 None（加载失败）。
    """
    dir_path = _SCRAPER_DIR / scraper_dir
    if str(dir_path) not in sys.path:
        sys.path.insert(0, str(dir_path))
    try:
        # 用全限定名避免缓存冲突
        full_name = f"{scraper_dir}_scraper_mod"
        if full_name in sys.modules:
            return sys.modules[full_name]
        spec = importlib.util.spec_from_file_location(
            full_name, dir_path / f"{module_name}.py"
        )
        if spec is None or spec.loader is None:
            return None
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    except Exception as e:  # noqa: BLE001
        logger.warning("加载爬虫 %s 失败: %s", scraper_dir, e)
        return None


class DxyCollector(DataCollector):
    """美元指数（新浪财经）。"""

    indicator_code = "DXY"
    indicator_name = "美元指数"
    category = "美国经济"
    source = "新浪财经"
    update_frequency = "5min"

    def fetch(self) -> Optional[CollectorResult]:
        mod = _load_scraper_module("dxy_scraper")
        if mod is None or not hasattr(mod, "scrape_dxy"):
            return self._fallback()
        try:
            data = mod.scrape_dxy()
            if not data:
                return self._fallback()
            price = float(data.get("current_price") or 0)
            prev = float(data.get("prev_close") or price)
            change = price - prev if prev else None
            change_pct = round(change / prev * 100, 2) if prev and change is not None else None
            return CollectorResult(
                indicator_code=self.indicator_code,
                indicator_name=self.indicator_name,
                category=self.category,
                value=price,
                change=round(change, 4) if change is not None else None,
                change_pct=change_pct,
                source=self.source,
                source_url=data.get("url", ""),
                update_frequency=self.update_frequency,
                raw_data=data,
            )
        except Exception as e:  # noqa: BLE001
            logger.warning("DXY 采集异常: %s", e)
            return self._fallback()

    def _fallback(self) -> Optional[CollectorResult]:
        """Playwright 不可用时用 yfinance 兜底。"""
        try:
            import yfinance as yf

            t = yf.Ticker("DX-Y.NYB")
            hist = t.history(period="2d")
            if hist.empty:
                return None
            price = float(hist["Close"].iloc[-1])
            prev = float(hist["Close"].iloc[-2]) if len(hist) > 1 else price
            change = price - prev
            return CollectorResult(
                indicator_code=self.indicator_code,
                indicator_name=self.indicator_name,
                category=self.category,
                value=round(price, 4),
                change=round(change, 4),
                change_pct=round(change / prev * 100, 2) if prev else None,
                source="yfinance",
                source_url="https://finance.yahoo.com/quote/DX-Y.NYB",
                update_frequency=self.update_frequency,
            )
        except Exception as e:  # noqa: BLE001
            logger.warning("DXY yfinance 兜底失败: %s", e)
            return None


class VixCollector(DataCollector):
    """VIX 恐慌指数（CBOE）。"""

    indicator_code = "VIX"
    indicator_name = "恐慌指数"
    category = "佐证表象"
    source = "CBOE"
    update_frequency = "5min"

    def fetch(self) -> Optional[CollectorResult]:
        mod = _load_scraper_module("vix_scraper")
        if mod is None:
            return self._fallback()
        try:
            scraper_cls = getattr(mod, "VIXScraper", None)
            if scraper_cls is None:
                return self._fallback()
            with scraper_cls(headless=True) as vix:
                data = vix.fetch_vix_data()
            if not data:
                return self._fallback()
            price = float(data.get("vix_spot_price") or 0)
            change = data.get("change_amount")
            change_pct = data.get("change_percent")
            return CollectorResult(
                indicator_code=self.indicator_code,
                indicator_name=self.indicator_name,
                category=self.category,
                value=price,
                change=float(change) if change is not None else None,
                change_pct=float(change_pct) if change_pct is not None else None,
                source=self.source,
                source_url="https://www.cboe.com/tradable_products/vix/",
                update_frequency=self.update_frequency,
                raw_data=data,
            )
        except Exception as e:  # noqa: BLE001
            logger.warning("VIX 采集异常: %s", e)
            return self._fallback()

    def _fallback(self) -> Optional[CollectorResult]:
        try:
            import yfinance as yf

            t = yf.Ticker("^VIX")
            hist = t.history(period="2d")
            if hist.empty:
                return None
            price = float(hist["Close"].iloc[-1])
            prev = float(hist["Close"].iloc[-2]) if len(hist) > 1 else price
            return CollectorResult(
                indicator_code=self.indicator_code,
                indicator_name=self.indicator_name,
                category=self.category,
                value=round(price, 2),
                change=round(price - prev, 2),
                change_pct=round((price - prev) / prev * 100, 2) if prev else None,
                source="yfinance",
                update_frequency=self.update_frequency,
            )
        except Exception as e:  # noqa: BLE001
            logger.warning("VIX yfinance 兜底失败: %s", e)
            return None


class TipsCollector(DataCollector):
    """10Y TIPS 实际利率（FRED DFII10，日频）。"""

    indicator_code = "TIPS10Y"
    indicator_name = "10年期实际利率"
    category = "美国经济"
    source = "FRED DFII10"
    update_frequency = "日频"
    realtime_inference = True  # 前向填充后进入实时推理

    def fetch(self) -> Optional[CollectorResult]:
        mod = _load_scraper_module("dfii10_scraper")
        if mod is None or not hasattr(mod, "scrape_dfii10"):
            return None
        try:
            data = mod.scrape_dfii10()
            if not data:
                return None
            value = float(data.get("latest_value") or 0)
            recent = data.get("recent_data") or []
            change = None
            if len(recent) >= 2:
                prev = recent[-2].get("value")
                if prev is not None:
                    change = round(value - float(prev), 4)
            change_pct = round(change / float(prev) * 100, 2) if change is not None and prev else None
            ts = datetime.now(timezone.utc)
            if data.get("latest_date"):
                try:
                    ts = datetime.strptime(data["latest_date"], "%Y-%m-%d").replace(
                        tzinfo=timezone.utc
                    )
                except ValueError:
                    pass
            return CollectorResult(
                indicator_code=self.indicator_code,
                indicator_name=self.indicator_name,
                category=self.category,
                value=value,
                change=change,
                change_pct=change_pct,
                source=self.source,
                source_url="https://fred.stlouisfed.org/series/DFII10",
                update_frequency=self.update_frequency,
                value_type="收益率",
                timestamp=ts,
                raw_data=data,
            )
        except Exception as e:  # noqa: BLE001
            logger.warning("TIPS 采集异常: %s", e)
            return None


class GprCollector(DataCollector):
    """地缘政治风险指数（GPR）。"""

    indicator_code = "GPR"
    indicator_name = "地缘风险"
    category = "地缘政治"
    source = "GPR 指数"
    update_frequency = "月度"

    def fetch(self) -> Optional[CollectorResult]:
        mod = _load_scraper_module("gpr_scraper")
        if mod is None or not hasattr(mod, "scrape_gpr"):
            return None
        try:
            data = mod.scrape_gpr()
            if not data:
                return None
            value = float(data.get("latest_value") or data.get("gpr_value") or 0)
            change = data.get("change")
            change_pct = data.get("change_pct")
            return CollectorResult(
                indicator_code=self.indicator_code,
                indicator_name=self.indicator_name,
                category=self.category,
                value=value,
                change=float(change) if change is not None else None,
                change_pct=float(change_pct) if change_pct is not None else None,
                source=self.source,
                source_url="https://www.matteoiacoviello.com/gpr.htm",
                update_frequency=self.update_frequency,
                raw_data=data,
            )
        except Exception as e:  # noqa: BLE001
            logger.warning("GPR 采集异常: %s", e)
            return None


class EpuCollector(DataCollector):
    """经济政策不确定性指数（EPU，月度，仅训练用）。"""

    indicator_code = "EPU"
    indicator_name = "经济政策不确定性"
    category = "美国经济"
    source = "EPU Index"
    update_frequency = "月度"
    realtime_inference = False

    def fetch(self) -> Optional[CollectorResult]:
        mod = _load_scraper_module("epu_scraper")
        if mod is None or not hasattr(mod, "scrape_epu"):
            return None
        try:
            data = mod.scrape_epu()
            if not data:
                return None
            value = float(data.get("latest_value") or 0)
            return CollectorResult(
                indicator_code=self.indicator_code,
                indicator_name=self.indicator_name,
                category=self.category,
                value=value,
                source=self.source,
                update_frequency=self.update_frequency,
                realtime_inference=False,
                raw_data=data,
            )
        except Exception as e:  # noqa: BLE001
            logger.warning("EPU 采集异常: %s", e)
            return None


class NewsCollector:
    """新闻采集器（NewsAPI），仅采集原始新闻，情感由 sentiment 模块处理。"""

    KEYWORDS = "gold OR XAU OR Fed OR inflation OR geopolitical"

    def fetch_latest(self, page: int = 1, page_size: int = 20) -> list[dict]:
        """采集最新新闻列表。返回原始新闻 dict 列表。"""
        if not settings.has_newsapi:
            logger.info("未配置 NEWSAPI_KEY，跳过新闻采集")
            return []
        try:
            import requests

            url = "https://newsapi.org/v2/everything"
            params = {
                "q": self.KEYWORDS,
                "language": "en",
                "sortBy": "publishedAt",
                "pageSize": page_size,
                "page": page,
                "apiKey": settings.newsapi_key,
            }
            resp = requests.get(url, params=params, timeout=15)
            resp.raise_for_status()
            articles = resp.json().get("articles", [])
            return [
                {
                    "title": a.get("title", ""),
                    "content": a.get("description", "") or a.get("content", ""),
                    "source": (a.get("source") or {}).get("name", ""),
                    "url": a.get("url", ""),
                    "published_at": a.get("publishedAt", ""),
                }
                for a in articles
            ]
        except Exception as e:  # noqa: BLE001
            logger.warning("新闻采集异常: %s", e)
            return []


class GoldPriceCollector:
    """XAU/USD 黄金价格采集器（多源容错）。

    优先 yfinance（海外），失败回退新浪财经实时金价接口（国内可达、无需 key）。
    任一链路成功即返回 (timestamp, price, volume)。时间戳统一使用采集发生的
    当前 UTC 时间，使前端走势图随时间滚动更新，而非停留在数据源的陈旧交易日。
    """

    SYMBOL = "GC=F"
    SINA_URL = "https://hq.sinajs.cn/list=XAUUSD"
    SINA_REFERER = "https://finance.sina.com.cn"
    # 实时外汇报价源（无需 key、stdlib 可达、按 tick 变动，提供真正"动起来"的行情）
    SWISSQUOTE_URL = "https://forex-data-feed.swissquote.com/public-quotes/bboquotes/instrument/XAU/USD"
    GOLDAPI_URL = "https://api.gold-api.com/price/XAU"

    def _urllib_get(self, url: str, timeout: float = 8.0) -> str:
        """绕过本机代理用 stdlib 拉取外网内容（环境 http_proxy 指向本地端口会致外网失败）。"""
        import urllib.request

        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="ignore")

    def fetch_sina(self) -> Optional[tuple[datetime, float, int]]:
        """新浪财经 XAU/USD 实时报价（国内可达、无需 key、零三方依赖）。

        返回形如 var hq_str_XAUUSD="时间,买价,卖价,当前价,成交量,...";
        取字段[3]=当前价、[4]=成交量。时间戳用采集当前 UTC 时间。
        注意：本环境下新浪的「当前价」字段常为陈旧快照，仅作为最后兜底。
        """
        import re

        try:
            text = self._urllib_get(self.SINA_URL, timeout=4)
        except Exception as e:  # noqa: BLE001
            logger.warning("新浪金价采集异常: %s", e)
            return None
        m = re.search(r'hq_str_XAUUSD="([^"]+)"', text)
        if not m:
            return None
        parts = m.group(1).split(",")
        # 字段: 时间,买价,卖价,当前价,成交量,今开,最高,最低,昨收,单位,日期
        if len(parts) < 5:
            return None
        try:
            price = float(parts[3])
        except (ValueError, IndexError):
            return None
        if price <= 0:
            return None
        vol_raw = parts[4].strip()
        volume = int(float(vol_raw)) if vol_raw not in ("", "0.0000") else 0
        return (datetime.now(timezone.utc), price, volume)

    def fetch_swissquote(self) -> Optional[tuple[datetime, float, int]]:
        """Swissquote 公开 XAU/USD 逐笔报价（首选实时源）。

        无需 key、stdlib 可达、按 tick 变动——能提供真正"动起来"的行情，
        解决旧方案（yfinance 未安装 / 新浪 latest 字段为陈旧快照）导致走势图
        看起来"不更新"的问题。取首条 spreadProfile 的 (bid+ask)/2 作为中间价，
        用行情自带的 ts（毫秒）作为时间戳，使走势图按真实行情时间滚动。
        """
        try:
            import json

            text = self._urllib_get(self.SWISSQUOTE_URL, timeout=4)
            data = json.loads(text)
            if not isinstance(data, list) or not data:
                return None
            for topo in data:
                spp = topo.get("spreadProfilePrices") or []
                if spp and "bid" in spp[0] and "ask" in spp[0]:
                    bid = float(spp[0]["bid"])
                    ask = float(spp[0]["ask"])
                    mid = round((bid + ask) / 2.0, 2)
                    if mid <= 0:
                        return None
                    # 时间戳用「采集发生的真实 UTC 时间」而非行情快照 ts：
                    # 行情快照 ts 约每 25s 才变一次，若用作主键会与 upsert 去重冲突，
                    # 导致连续两次采集拿到相同 ts 被丢弃、图表看似不动。用 now() 保证
                    # 每个 30s tick 都是唯一且递增的新点，走势图稳定向前滚动。
                    return (datetime.now(timezone.utc), mid, 0)
        except Exception as e:  # noqa: BLE001
            logger.warning("Swissquote 金价采集异常: %s", e)
        return None

    def fetch_goldapi(self) -> Optional[tuple[datetime, float, int]]:
        """gold-api.com 实时金价（无需 key），作为 Swissquote 的次级兜底。"""
        try:
            import json

            text = self._urllib_get(self.GOLDAPI_URL, timeout=4)
            d = json.loads(text)
            price = float(d.get("price") or 0)
            if price <= 0:
                return None
            # 时间戳用采集发生的真实 UTC 时间（理由同 fetch_swissquote），保证每个
            # tick 唯一递增、不会被 upsert 去重掉。
            return (datetime.now(timezone.utc), round(price, 2), 0)
        except Exception as e:  # noqa: BLE001
            logger.warning("gold-api 金价采集异常: %s", e)
        return None

    def fetch_latest(self, timeout: float = 8.0) -> Optional[tuple[datetime, float, int]]:
        """并行多源容错，取第一个成功返回的实时金价。

        把 Swissquote / gold-api / 新浪 三个源各自放进守护线程**并行**拉取，
        谁先成功就用谁。这样即便某个源握手挂起（如 Swissquote SSL 超时），
        其它源仍可快速交付；整轮耗时被 deadline 牢牢限制在约 timeout 秒内，
        不会再因「串行叠加（6s×3≈18s）」超过 30s 调度间隔，导致下一拍
        _job_collect_gold 被 APScheduler 以「max_instances 达上限」跳过，
        从而保证页面实时走势每个 tick 都不丢。各源内部 socket 超时已收紧到 4s。
        """
        import concurrent.futures as _cf

        fetchers = (self.fetch_swissquote, self.fetch_goldapi, self.fetch_sina)

        def _safe(fn):
            try:
                return fn()
            except Exception as e:  # noqa: BLE001
                logger.debug("%s 采集异常: %s", fn.__name__, e)
                return None

        def _safe_result(fut):
            try:
                return fut.result()
            except Exception:  # noqa: BLE001
                return None

        ex = _cf.ThreadPoolExecutor(max_workers=len(fetchers))
        try:
            futs = [ex.submit(_safe, f) for f in fetchers]
            # 先等「第一个完成」的源（最快返回者），不让慢源阻塞整体返回
            done, pending = _cf.wait(
                futs, timeout=timeout, return_when=_cf.FIRST_COMPLETED
            )
            for fut in done:
                r = _safe_result(fut)
                if r is not None:
                    return r
            # 首个完成的源都失败，再看其余源（总耗时仍受 timeout 限制）
            for fut in _cf.as_completed(pending, timeout=max(0.1, timeout)):
                r = _safe_result(fut)
                if r is not None:
                    return r
            logger.warning("金价采集失败：Swissquote / gold-api / 新浪 均不可用")
            return None
        except _cf.TimeoutError:
            logger.warning("金价采集在 %ss 内无源返回，跳过本轮", timeout)
            return None
        finally:
            # 关键：不等慢源线程跑完（否则会等到其 socket 超时，拖慢每个 tick），
            # 直接放弃尚未完成的任务，运行中的线程会在各自 socket 超时后自行结束。
            ex.shutdown(wait=False, cancel_futures=True)

    def fetch_series(self, period: str = "1d", interval: str = "5m") -> list[tuple]:
        """返回 [(timestamp, price, volume), ...]。实时源为逐笔报价无历史，
        故直接返回最近一次实时点；若不可用返回空列表。"""
        r = self.fetch_latest()
        return [r] if r else []
