"""
Federal Reserve 新闻抓取器

目标（参考 docs/news_sample/www.federalreserve.gov:newsevents.htm.png 红框）：
- Press Releases 列表
- Speeches 列表
- Testimony 列表
每个条目包含：标题、链接、日期， speeches/testimony 还含讲话人。
"""
import re

from playwright.async_api import Locator, Page

from ..models import RawNewsItem
from .base import BaseScraper


async def _safe_text(locator: Locator, timeout: int = 1_000) -> str:
    try:
        return await locator.inner_text(timeout=timeout)
    except Exception:
        return ""


class FedScraper(BaseScraper):
    name = "federal_reserve"
    display_name = "Federal Reserve"
    base_url = "https://www.federalreserve.gov"

    async def scrape(self, page: Page) -> list[RawNewsItem]:
        await self._navigate(page, f"{self.base_url}/newsevents.htm")

        items: list[RawNewsItem] = []

        sections = [
            ("Press Releases", "pressReleases"),
            ("Speeches", "speeches"),
            ("Testimony", "testimony"),
        ]

        for category, anchor in sections:
            section_items = await self._extract_section(page, category, anchor)
            items.extend(section_items)
            if len(items) >= self.max_items:
                break

        return items[: self.max_items]

    async def _extract_section(
        self, page: Page, category: str, anchor: str
    ) -> list[RawNewsItem]:
        """提取单个栏目下的新闻条目"""
        items: list[RawNewsItem] = []

        locators = [
            f"//*[@id='{anchor}']//div[contains(@class,'row')][position()<=5]",
            f"//h2[contains(text(),'{category}')]/following::div[contains(@class,'row')][position()<=5]",
            f"//h2[contains(text(),'{category}')]/following::a[not(contains(@href,'javascript'))][position()<=10]",
        ]

        for locator in locators:
            rows = await page.locator(locator).all()
            if rows:
                for row in rows:
                    item = await self._parse_row(row, category)
                    if item and item.title:
                        items.append(item)
                if items:
                    break

        return items

    async def _parse_row(self, row: Locator, category: str) -> RawNewsItem | None:
        try:
            link_locator = row.locator("a").first
            title = await _safe_text(link_locator, timeout=2_000)
            href = await row.locator("a").first.get_attribute("href", timeout=2_000)

            if not title:
                title = await _safe_text(row, timeout=2_000)

            lines = [line.strip() for line in title.split("\n") if line.strip()]
            if not lines:
                return None

            # 第一行通常是标题；包含日期格式的行单独作为 published_at
            date_text = ""
            for line in lines[1:]:
                if re.search(r"\d{1,2}/\d{1,2}/\d{2,4}|\d{4}", line) and len(line) < 60:
                    date_text = line
                    break

            clean_title = lines[0]

            return RawNewsItem(
                source=self.display_name,
                title=self._clean_text(clean_title),
                url=self._abs_url(href),
                published_at=self._clean_text(date_text) if date_text else None,
                summary=None,
                category=category,
            )
        except Exception:
            return None
