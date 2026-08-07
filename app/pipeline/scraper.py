"""
页面爬虫：抓取黄金价格历史页面，解析 HTML 表格为结构化记录。

- fetch()   : 通过 requests 拉取目标页面（可配置 URL）；无网络/未配置时回退到内置样本 HTML
- parse()   : 用 BeautifulSoup 解析 <table>，按表头自适应识别列（中英文表头均可）
- normalize(): 清洗——日期/数值解析、价格区间校验、OHLC 一致性校验、剔除非法行

落库见 app.pipeline.store，端到端编排见 app.pipeline.run。
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Optional

import requests
from bs4 import BeautifulSoup

try:  # python-dateutil 为项目既有依赖，缺失时回退到有限格式解析
    from dateutil import parser as _date_parser
    _HAS_DATEUTIL = True
except Exception:  # pragma: no cover
    _HAS_DATEUTIL = False

logger = logging.getLogger(__name__)

DEFAULT_URL = "https://example.com/gold/historical"  # 占位：替换为你真实的黄金价格页面
USER_AGENT = "Mozilla/5.0 (compatible; GoldPriceScraper/1.0)"

# 合理价格区间（USD/oz），用于字段正确性校验
PRICE_MIN = 1.0
PRICE_MAX = 100_000.0

# 表头别名 -> 字段名（忽略大小写、子串匹配，支持中英文）
COLUMN_ALIASES = {
    "date": "quote_date", "时间": "quote_date", "日期": "quote_date",
    "open": "open", "开盘": "open",
    "high": "high", "最高": "high",
    "low": "low", "最低": "low",
    "close": "close", "price": "close", "收盘": "close", "last": "close", "最新": "close",
    "vol": "volume", "volume": "volume", "成交量": "volume",
    "currency": "currency", "货币": "currency",
    "symbol": "symbol", "标的": "symbol",
}

# 内置样本：结构与真实历史价格表一致，用于离线运行与单元测试。
# 注：含两行非法数据（high<low、close=N/A），用于验证清洗丢弃逻辑。
FIXTURE_HTML = """<!DOCTYPE html>
<html><head><title>Gold Historical Prices</title></head>
<body>
<table class="historical">
  <thead>
    <tr><th>Date</th><th>Open</th><th>High</th><th>Low</th><th>Close</th><th>Volume</th><th>Currency</th></tr>
  </thead>
  <tbody>
    <tr><td>2026-08-01</td><td>2,035.10</td><td>2,040.50</td><td>2,030.00</td><td>2,038.20</td><td>1,200,000</td><td>USD</td></tr>
    <tr><td>2026-08-02</td><td>2,038.20</td><td>2,045.00</td><td>2,036.00</td><td>2,042.75</td><td>980,500</td><td>USD</td></tr>
    <tr><td>2026-08-03</td><td>2,042.75</td><td>2,039.00</td><td>2,030.00</td><td>2,035.00</td><td>1,100,000</td><td>USD</td></tr>
    <tr><td>2026-08-04</td><td>2,035.00</td><td>abc</td><td>2,028.00</td><td>2,031.50</td><td>1,050,000</td><td>USD</td></tr>
    <tr><td>2026-08-05</td><td>2,031.50</td><td>2,036.00</td><td>2,029.00</td><td>N/A</td><td>1,020,000</td><td>USD</td></tr>
  </tbody>
</table>
</body></html>"""


@dataclass
class ScrapeRecord:
    """一条清洗后的黄金价格记录（已校验、可直接落库）。"""

    source: str
    symbol: str
    quote_date: date
    open: Optional[float]
    high: Optional[float]
    low: Optional[float]
    close: float
    volume: Optional[float]
    currency: str


class GoldPriceScraper:
    """黄金价格页面爬虫：抓取 -> 解析 -> 清洗。"""

    def __init__(self, source: str = "gold_scraper", timeout: int = 15) -> None:
        self.source = source
        self.timeout = timeout

    # —— 采集 ——
    def fetch(self, url: Optional[str] = None, use_fixture: bool = False) -> str:
        """拉取目标页面 HTML；未配置 URL 或请求失败时回退内置样本。"""
        if use_fixture or not url:
            return FIXTURE_HTML
        try:
            resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=self.timeout)
            resp.raise_for_status()
            return resp.text
        except requests.RequestException as exc:  # 网络不可达等
            logger.warning("抓取 %s 失败，回退样本数据: %s", url, exc)
            return FIXTURE_HTML

    # —— 解析 ——
    def parse(self, html: str) -> list[dict]:
        """解析 HTML 表格为原始字段字典列表（值为字符串，未经清洗）。"""
        soup = BeautifulSoup(html, "html.parser")
        table = soup.find("table")
        if table is None:
            logger.warning("页面中未找到 <table>")
            return []

        # 表头：优先 <th>，否则用首行 <td>
        header_cells = [th.get_text(strip=True) for th in table.find_all("th")]
        start = 1
        if not header_cells:
            first_row = table.find("tr")
            header_cells = [td.get_text(strip=True) for td in first_row.find_all("td")] if first_row else []
            start = 0

        col_map = self._map_columns(header_cells)
        if "close" not in col_map.values() or "quote_date" not in col_map.values():
            logger.warning("未识别到必要列（date/close），无法解析")
            return []

        rows: list[dict] = []
        for tr in table.find_all("tr")[start:]:
            cells = [td.get_text(strip=True) for td in tr.find_all(["td", "th"])]
            if not cells:
                continue
            rec: dict = {}
            for idx, field_name in col_map.items():
                if idx < len(cells):
                    rec[field_name] = cells[idx]
            if rec:
                rows.append(rec)
        logger.info("解析到 %d 行原始数据", len(rows))
        return rows

    @staticmethod
    def _map_columns(headers: list[str]) -> dict[int, str]:
        """将表头下标映射到字段名（子串匹配别名）。"""
        col_map: dict[int, str] = {}
        for i, h in enumerate(headers):
            key = h.strip().lower()
            for alias, field_name in COLUMN_ALIASES.items():
                if alias in key:
                    col_map[i] = field_name
                    break
        return col_map

    # —— 清洗 ——
    def normalize(self, raw: dict) -> Optional[ScrapeRecord]:
        """将一行原始数据清洗为 ScrapeRecord；非法则返回 None（被丢弃）。"""
        d = self._parse_date(raw.get("quote_date"))
        if d is None:
            return None
        close = self._parse_float(raw.get("close"))
        if close is None or not (PRICE_MIN <= close <= PRICE_MAX):
            return None

        o = self._parse_float(raw.get("open"))
        h = self._parse_float(raw.get("high"))
        l = self._parse_float(raw.get("low"))
        v = self._parse_float(raw.get("volume"))

        # OHLC 一致性：high >= max(open, close)；low <= min(open, close)
        highs = [x for x in (o, close, h) if x is not None]
        lows = [x for x in (o, close, l) if x is not None]
        if h is not None and h < max(highs):
            return None
        if l is not None and l > min(lows):
            return None
        if v is not None and v < 0:  # 负成交量视为缺失
            v = None

        symbol = str(raw.get("symbol") or "XAU/USD").strip() or "XAU/USD"
        currency = str(raw.get("currency") or "USD").strip() or "USD"
        return ScrapeRecord(
            source=self.source,
            symbol=symbol,
            quote_date=d,
            open=o, high=h, low=l, close=close,
            volume=v, currency=currency,
        )

    # —— 端到端（抓取 + 清洗）——
    def scrape(self, url: Optional[str] = None, use_fixture: bool = False) -> list[ScrapeRecord]:
        html = self.fetch(url, use_fixture=use_fixture)
        raw_rows = self.parse(html)
        out: list[ScrapeRecord] = []
        for r in raw_rows:
            rec = self.normalize(r)
            if rec is not None:
                out.append(rec)
        logger.info("解析 %d 行，清洗后有效 %d 行", len(raw_rows), len(out))
        return out

    # —— 解析辅助 ——
    @staticmethod
    def _parse_date(val) -> Optional[date]:
        if val is None:
            return None
        s = str(val).strip()
        if not s:
            return None
        if _HAS_DATEUTIL:
            try:
                return _date_parser.parse(s).date()
            except (ValueError, OverflowError):
                return None
        for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%d-%m-%Y", "%d/%m/%Y"):
            try:
                return datetime.strptime(s, fmt).date()
            except ValueError:
                continue
        return None

    @staticmethod
    def _parse_float(val) -> Optional[float]:
        if val is None:
            return None
        s = str(val).strip()
        if not s or s.lower() in ("-", "n/a", "na", "null", "none"):
            return None
        s = s.replace(",", "").replace("$", "").strip()
        try:
            return float(s)
        except ValueError:
            m = re.search(r"-?\d+(?:\.\d+)?", s)
            return float(m.group()) if m else None
