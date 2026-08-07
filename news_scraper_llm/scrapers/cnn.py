"""
CNN International 抓取器

目标（参考 docs/news_sample/edition.cnn.com.png 红框）：
- 首页头条大标题
- 次要新闻标题
提取：标题、链接
"""
from playwright.async_api import Locator, Page

from ..models import RawNewsItem
from .base import BaseScraper


async def _safe_text(locator: Locator, timeout: int = 1_000) -> str:
    try:
        return await locator.inner_text(timeout=timeout)
    except Exception:
        return ""


async def _safe_attr(locator: Locator, attr: str, timeout: int = 1_000) -> str | None:
    try:
        return await locator.get_attribute(attr, timeout=timeout)
    except Exception:
        return None


class CNNScraper(BaseScraper):
    name = "cnn"
    display_name = "CNN International"
    base_url = "https://edition.cnn.com"

    async def scrape(self, page: Page) -> list[RawNewsItem]:
        await self._navigate(page, self.base_url)

        items: list[RawNewsItem] = []
        seen_titles: set[str] = set()

        # CNN 常见 headline 选择器
        selectors = [
            ".container__headline-text",
            ".card__headline__text",
            ".headline__text",
            ".media__video__title",
            "h2 a[data-link-type='article']",
            "h3 a[data-link-type='article']",
        ]

        for sel in selectors:
            links = await page.locator(sel).all()
            for link in links:
                try:
                    # 获取 clickable 元素与标题文本
                    tag_name = await link.evaluate(
                        "el => el.tagName.toLowerCase()", timeout=1_000
                    )
                    if tag_name == "a":
                        title_el = link
                    else:
                        # 尝试父级 a 标签
                        parent = link.locator("xpath=..")
                        parent_tag = await parent.evaluate(
                            "el => el.tagName.toLowerCase()", timeout=1_000
                        )
                        title_el = parent if parent_tag == "a" else link

                    title = await _safe_text(title_el, timeout=1_000)
                    href = None
                    if title_el == link and tag_name == "a":
                        href = await _safe_attr(title_el, "href", timeout=1_000)
                    else:
                        href = await _safe_attr(parent, "href", timeout=1_000)

                    clean = self._clean_text(title)
                    if clean and clean not in seen_titles and len(clean) > 10:
                        items.append(RawNewsItem(
                            source=self.display_name,
                            title=clean,
                            url=self._abs_url(href),
                            published_at=None,
                            summary=None,
                            category="Headline",
                        ))
                        seen_titles.add(clean)
                except Exception:
                    continue
            if len(items) >= self.max_items:
                break

        return items[: self.max_items]
