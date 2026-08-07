"""
AP News 抓取器

目标（参考 docs/news_sample/apnews.com.png 红框）：
- 首页主头条（Hero）
- More Coverage 区域列表
提取：标题、链接、阅读时间/摘要
"""
from playwright.async_api import Page

from ..models import RawNewsItem
from .base import BaseScraper


class APNewsScraper(BaseScraper):
    name = "ap_news"
    display_name = "Associated Press"
    base_url = "https://apnews.com"

    async def scrape(self, page: Page) -> list[RawNewsItem]:
        await self._navigate(page, self.base_url)

        items: list[RawNewsItem] = []

        # 1. Hero / 主头条
        hero_selectors = [
            ".PagePromoCategory-Hero .PagePromo-title a",
            ".Hero .PagePromo-title a",
            "[data-key='hero'] .PagePromo-title a",
            ".PagePromo-title a",  # 兜底：取第一个 PagePromo-title
        ]
        for sel in hero_selectors:
            hero = page.locator(sel).first
            try:
                await hero.wait_for(state="visible", timeout=5_000)
                title = await hero.inner_text()
                href = await hero.get_attribute("href")
                if title.strip():
                    items.append(RawNewsItem(
                        source=self.display_name,
                        title=self._clean_text(title),
                        url=self._abs_url(href),
                        published_at=None,
                        summary=None,
                        category="Top Story",
                    ))
                    break
            except Exception:
                continue

        # 2. More Coverage / 其他主推新闻
        promo_selectors = [
            ".PagePromo-title a",
            ".PagePromoContent .PagePromo-title a",
            ".FeedCard .PagePromo-title a",
        ]
        seen_titles = {it.title for it in items}
        for sel in promo_selectors:
            links = await page.locator(sel).all()
            for link in links:
                try:
                    title = await link.inner_text()
                    href = await link.get_attribute("href")
                    clean = self._clean_text(title)
                    if clean and clean not in seen_titles:
                        items.append(RawNewsItem(
                            source=self.display_name,
                            title=clean,
                            url=self._abs_url(href),
                            published_at=None,
                            summary=None,
                            category="Coverage",
                        ))
                        seen_titles.add(clean)
                except Exception:
                    continue
            if len(items) >= self.max_items:
                break

        return items[: self.max_items]
