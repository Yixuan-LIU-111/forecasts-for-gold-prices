"""
抓取器基类
"""
from abc import ABC, abstractmethod
from urllib.parse import urljoin

from playwright.async_api import Page

from ..config import settings
from ..models import RawNewsItem


class BaseScraper(ABC):
    """站点抓取器抽象基类"""

    name: str = ""
    display_name: str = ""
    base_url: str = ""

    def __init__(self, max_items: int = 10):
        self.max_items = max_items

    @abstractmethod
    async def scrape(self, page: Page) -> list[RawNewsItem]:
        """执行抓取，返回 RawNewsItem 列表"""
        ...

    def _abs_url(self, href: str | None) -> str | None:
        """补全相对链接"""
        if not href:
            return None
        return urljoin(self.base_url, href.strip())

    def _clean_text(self, text: str | None) -> str:
        """清洗文本"""
        return " ".join((text or "").split())

    async def _navigate(self, page: Page, url: str) -> None:
        """统一导航：用 domcontentloaded 尽快返回，避免 networkidle 在重站点上长时间挂起。

        重站点（CNN/AP/Fed）充斥广告与统计脚本，networkidle 几乎永远等不到，
        因此仅用短超时尝试，失败则忽略并继续后续解析。
        """
        await page.goto(url, wait_until="domcontentloaded", timeout=settings.page_timeout_ms)
        try:
            await page.wait_for_load_state("networkidle", timeout=5_000)
        except Exception:
            pass
        # JS 渲染内容通常需要一点时间，给一个短暂的 settle 等待
        await page.wait_for_timeout(1_500)
