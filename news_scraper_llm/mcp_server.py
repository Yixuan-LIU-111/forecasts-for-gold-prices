"""
可选：将新闻抓取 + 情感分析封装为 MCP Tool

依赖：pip install mcp
运行：python news_scraper_llm/mcp_server.py
测试：npx @modelcontextprotocol/inspector python news_scraper_llm/mcp_server.py
"""
import asyncio
from typing import Literal

from mcp.server.fastmcp import FastMCP

from news_scraper_llm.analyzer import SentimentAnalyzer
from news_scraper_llm.config import settings
from news_scraper_llm.models import AnalyzedNewsItem
from news_scraper_llm.scrapers import (
    APNewsScraper,
    CNNScraper,
    FedScraper,
    WhiteHouseScraper,
)
from news_scraper_llm.scrapers.engine import ScrapingEngine

mcp = FastMCP("news_sentiment_scraper")


@mcp.tool(
    name="scrape_news_sentiment",
    description=(
        "抓取美联储、白宫、AP News、CNN International 最新新闻，"
        "并使用 LLM 输出情感分值（-1~+1）与离散标签（positive/negative/neutral）。"
    ),
)
async def scrape_news_sentiment(
    sites: list[Literal["fed", "whitehouse", "apnews", "cnn"]] | None = None,
    max_items_per_site: int = 5,
    sentiment_mode: Literal["general", "gold"] = "general",
) -> list[dict]:
    """
    MCP Tool：抓取指定站点新闻并做情感分析。

    Args:
        sites: 站点列表，默认全部 4 个
        max_items_per_site: 每个站点最大抓取条数
        sentiment_mode: general（通用情感）或 gold（黄金利多/利空）
    """
    settings.max_items_per_site = max_items_per_site
    settings.sentiment_mode = sentiment_mode

    site_map = {
        "fed": FedScraper,
        "whitehouse": WhiteHouseScraper,
        "apnews": APNewsScraper,
        "cnn": CNNScraper,
    }
    sites = sites or list(site_map.keys())

    engine = ScrapingEngine()
    for key in sites:
        engine.add(site_map[key](max_items=max_items_per_site))

    raw_items = await engine.run()
    analyzer = SentimentAnalyzer()
    pairs = await analyzer.analyze_many(raw_items)

    results: list[AnalyzedNewsItem] = []
    for raw, sent in pairs:
        results.append(AnalyzedNewsItem(
            source=raw.source,
            title=raw.title,
            url=raw.url,
            published_at=raw.published_at,
            summary=raw.summary,
            category=raw.category,
            scraped_at=raw.scraped_at,
            sentiment_score=sent.sentiment_score,
            sentiment_label=sent.sentiment_label,
            topic=sent.topic,
            confidence=sent.confidence,
            key_sentence=sent.key_sentence,
            sentiment_mode=sentiment_mode,
        ))

    return [r.model_dump(mode="json") for r in results]


if __name__ == "__main__":
    mcp.run(transport="stdio")
