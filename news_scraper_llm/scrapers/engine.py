"""
抓取引擎：统一调度多个 Playwright 抓取器
"""
import asyncio

from playwright.async_api import async_playwright

from ..config import settings
from ..models import RawNewsItem
from ..summary_fetcher import enrich_summaries
from .base import BaseScraper


class ScrapingEngine:
    """多站点抓取引擎"""

    def __init__(
        self,
        scrapers: list[BaseScraper] | None = None,
        fetch_article_summaries: bool | None = None,
    ):
        self.scrapers = scrapers or []
        self.fetch_article_summaries = (
            fetch_article_summaries
            if fetch_article_summaries is not None
            else getattr(settings, "fetch_article_summaries", False)
        )

    def add(self, scraper: BaseScraper) -> "ScrapingEngine":
        self.scrapers.append(scraper)
        return self

    async def run(self) -> list[RawNewsItem]:
        """
        启动浏览器，依次运行每个抓取器。
        每个站点使用独立 page， polite_delay_ms 控制站点内请求间隔。
        """
        all_items: list[RawNewsItem] = []

        async with async_playwright() as p:
            browser = await p[settings.browser].launch(headless=settings.headless)
            context = await browser.new_context(
                user_agent=settings.user_agent,
                viewport={"width": 1280, "height": 900},
            )

            try:
                for scraper in self.scrapers:
                    page = await context.new_page()
                    try:
                        items = await scraper.scrape(page)
                        all_items.extend(items)
                    except Exception as exc:
                        #  actionable error：单个站点失败不影响其他站点
                        print(f"[ERROR] {scraper.display_name} 抓取失败: {exc}")
                    finally:
                        await page.close()
                    # 站点间礼貌等待
                    await asyncio.sleep(settings.polite_delay_ms / 1000)

                # 可选：进入详情页补充正文摘要
                if self.fetch_article_summaries and all_items:
                    summary_page = await context.new_page()
                    try:
                        await enrich_summaries(
                            summary_page, all_items, enabled=True
                        )
                    except Exception as exc:
                        print(f"[WARN] 摘要补充失败: {exc}")
                    finally:
                        await summary_page.close()
            finally:
                await context.close()
                await browser.close()

        return all_items
