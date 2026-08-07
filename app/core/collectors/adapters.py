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
    """XAU/USD 黄金价格采集器（yfinance）。"""

    SYMBOL = "GC=F"

    def fetch_latest(self) -> Optional[tuple[datetime, float, int]]:
        """返回 (timestamp, price, volume)。"""
        try:
            import yfinance as yf

            t = yf.Ticker(self.SYMBOL)
            hist = t.history(period="1d", interval="1m")
            if hist.empty:
                return None
            last = hist.iloc[-1]
            ts = hist.index[-1].to_pydatetime().replace(tzinfo=timezone.utc)
            return (ts, float(last["Close"]), int(last.get("Volume", 0) or 0))
        except Exception as e:  # noqa: BLE001
            logger.warning("金价采集异常: %s", e)
            return None

    def fetch_series(self, period: str = "1d", interval: str = "5m") -> list[tuple]:
        """返回 [(timestamp, price, volume), ...]。"""
        try:
            import yfinance as yf

            t = yf.Ticker(self.SYMBOL)
            hist = t.history(period=period, interval=interval)
            if hist.empty:
                return []
            rows = []
            for ts, row in hist.iterrows():
                rows.append(
                    (
                        ts.to_pydatetime().replace(tzinfo=timezone.utc),
                        float(row["Close"]),
                        int(row.get("Volume", 0) or 0),
                    )
                )
            return rows
        except Exception as e:  # noqa: BLE001
            logger.warning("金价序列采集异常: %s", e)
            return []
