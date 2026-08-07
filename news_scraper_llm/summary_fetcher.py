"""
正文摘要提取器

当列表页未提供摘要时，可选进入文章详情页提取首段或 meta description。
默认关闭，可通过 FETCH_ARTICLE_SUMMARY=true 开启。
"""
from playwright.async_api import Page

from .models import RawNewsItem


_SUMMARY_MAX_CHARS = 800


async def fetch_summary(page: Page, url: str) -> str:
    """
    访问文章页并提取摘要。
    策略：
    1. meta[name='description'] / og:description
    2. 文章首段 p（排除导航、广告等常见噪音）
    """
    try:
        await page.goto(url, timeout=30_000)
        await page.wait_for_load_state("networkidle")

        # 1. meta description
        for meta_sel in [
            "meta[name='description']",
            "meta[property='og:description']",
            "meta[name='twitter:description']",
        ]:
            meta = page.locator(meta_sel).first
            try:
                content = await meta.get_attribute("content", timeout=2_000)
                if content and len(content.strip()) > 30:
                    return _truncate(content.strip())
            except Exception:
                continue

        # 2. 首段：排除明显非正文段落
        paragraph_sels = [
            "article p",
            ".article-body p",
            ".story-body p",
            ".entry-content p",
            ".wp-block-post-content p",
            "#content p",
            "main p",
            "p",
        ]
        for sel in paragraph_sels:
            paragraphs = await page.locator(sel).all()
            for p in paragraphs:
                try:
                    text = await p.inner_text(timeout=1_000)
                    clean = " ".join(text.split())
                    if _is_valid_paragraph(clean):
                        return _truncate(clean)
                except Exception:
                    continue

        return ""
    except Exception:
        return ""


def _is_valid_paragraph(text: str) -> bool:
    """过滤导航、版权、广告等噪音段落"""
    if len(text) < 40:
        return False
    noise_keywords = [
        "copyright", "all rights reserved", "cookie", "privacy policy",
        "terms of use", "subscribe", "sign up", "advertisement", "follow us",
    ]
    lower = text.lower()
    return not any(k in lower for k in noise_keywords)


def _truncate(text: str) -> str:
    if len(text) <= _SUMMARY_MAX_CHARS:
        return text
    return text[:_SUMMARY_MAX_CHARS].rsplit(" ", 1)[0] + "..."


async def enrich_summaries(
    page: Page, items: list[RawNewsItem], enabled: bool = False
) -> list[RawNewsItem]:
    """为缺少 summary 的条目补充详情页摘要"""
    if not enabled:
        return items

    for item in items:
        if item.summary or not item.url:
            continue
        summary = await fetch_summary(page, item.url)
        if summary:
            item.summary = summary
    return items
