"""
White House 新闻抓取器

目标（参考 docs/news_sample/www.whitehouse.gov:news.png 红框）：
- /news/ 页面新闻卡片列表
- 提取：标题、链接、分类（Briefings & Statements 等）、日期
"""
from playwright.async_api import Locator, Page

from ..models import RawNewsItem
from .base import BaseScraper


async def _safe_text(locator: Locator, timeout: int = 1_000) -> str:
    """安全获取 locator 文本，失败返回空字符串"""
    try:
        return await locator.inner_text(timeout=timeout)
    except Exception:
        return ""


async def _safe_attr(locator: Locator, attr: str, timeout: int = 1_000) -> str | None:
    """安全获取 locator 属性，失败返回 None"""
    try:
        return await locator.get_attribute(attr, timeout=timeout)
    except Exception:
        return None


class WhiteHouseScraper(BaseScraper):
    name = "white_house"
    display_name = "The White House"
    base_url = "https://www.whitehouse.gov"

    async def scrape(self, page: Page) -> list[RawNewsItem]:
        await self._navigate(page, f"{self.base_url}/news/")

        items: list[RawNewsItem] = []

        # WordPress 常见文章列表选择器（按优先级）
        selectors = [
            "article.wp-block-post",
            ".wp-block-post-template > li",
            ".news-articles article",
            ".post-listing article",
            "article.type-post",
        ]

        for selector in selectors:
            cards = await page.locator(selector).all()
            if cards:
                for card in cards[: self.max_items]:
                    item = await self._parse_card(card)
                    if item and item.title:
                        items.append(item)
                if items:
                    break

        return items[: self.max_items]

    async def _parse_card(self, card: Locator) -> RawNewsItem | None:
        try:
            # 标题与链接
            title_locators = [
                card.locator("h2 a").first,
                card.locator("h3 a").first,
                card.locator(".wp-block-post-title a").first,
                card.locator("a").first,
            ]
            title = ""
            href = None
            for loc in title_locators:
                text = await _safe_text(loc, timeout=2_000)
                if text.strip():
                    title = text.strip()
                    href = await _safe_attr(loc, "href", timeout=2_000)
                    break

            if not title:
                return None

            # 日期
            date = ""
            for date_sel in ["time", ".wp-block-post-date", ".entry-date", ".date"]:
                txt = await _safe_text(card.locator(date_sel).first, timeout=1_000)
                if txt.strip():
                    date = txt.strip()
                    break

            # 分类
            category = ""
            for cat_sel in [
                ".taxonomy-category a",
                ".wp-block-post-terms a",
                ".category a",
                ".post-category",
            ]:
                txt = await _safe_text(card.locator(cat_sel).first, timeout=1_000)
                if txt.strip():
                    category = txt.strip()
                    break

            return RawNewsItem(
                source=self.display_name,
                title=self._clean_text(title),
                url=self._abs_url(href),
                published_at=self._clean_text(date) if date else None,
                summary=None,
                category=category or "News",
            )
        except Exception:
            return None
