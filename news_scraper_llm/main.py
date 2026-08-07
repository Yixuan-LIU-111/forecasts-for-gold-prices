"""
CLI 入口：抓取 4 个站点新闻 → （缓存筛选）→ LLM 情感分析 → 持久化入库

完整链路（需求 1）：
    新闻抓取(Playwright)
      → 分析前筛选：已分析过的 URL 直接跳过（省 LLM 调用，C-2）
      → LLM 情感分析（结构化输出 / 失败重试 / 降级）
      → 落库：news 按 url 去重 + sentiment 按 (news_id,模型,模式) 幂等 upsert
      → 同时保留 JSON/CSV 文件输出（便于人工抽查）

用法：
    # 从父目录 forecasts for gold prices 执行（注意不是 cd 进 news_scraper_llm）
    cd "/Users/echo/Desktop/forecasts for gold prices"
    news_scraper_llm/.venv/bin/python -m news_scraper_llm

依赖：除既有依赖外，需 SQLAlchemy（pip install sqlalchemy），用于落库。
"""
import asyncio
import logging
import os
import sys
import time
from pathlib import Path

# 允许从仓库根目录直接运行：python -m news_scraper_llm
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

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
from news_scraper_llm.storage import save_results

try:
    from news_scraper_llm import db as db_layer
    _HAS_DB = True
except ImportError:
    _HAS_DB = False

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("news_scraper_llm")


def build_scrapers() -> ScrapingEngine:
    """组装 4 个站点抓取器"""
    engine = ScrapingEngine()
    engine.add(FedScraper(max_items=settings.max_items_per_site))
    engine.add(WhiteHouseScraper(max_items=settings.max_items_per_site))
    engine.add(APNewsScraper(max_items=settings.max_items_per_site))
    engine.add(CNNScraper(max_items=settings.max_items_per_site))
    return engine


def _build_analyzed(items) -> list[AnalyzedNewsItem]:
    """将 (raw, sentiment, model_version) 转为可输出的 AnalyzedNewsItem。"""
    out: list[AnalyzedNewsItem] = []
    for raw, sentiment, _mv in items:
        out.append(AnalyzedNewsItem(
            source=raw.source,
            title=raw.title,
            url=raw.url,
            published_at=raw.published_at,
            summary=raw.summary,
            category=raw.category,
            scraped_at=raw.scraped_at,
            sentiment_score=sentiment.sentiment_score,
            sentiment_label=sentiment.sentiment_label,
            topic=sentiment.topic,
            confidence=sentiment.confidence,
            key_sentence=sentiment.key_sentence,
            sentiment_mode=settings.sentiment_mode,
        ))
    return out


async def main() -> None:
    t0 = time.time()
    if not settings.openai_api_key or settings.openai_api_key == "sk-xxx":
        print("[ERROR] 请在 .env 中设置 OPENAI_API_KEY")
        sys.exit(1)

    logger.info("情感分析模式: %s", settings.sentiment_mode)
    logger.info("开始抓取 4 个站点新闻...")

    engine = build_scrapers()
    raw_items = await engine.run()

    if not raw_items:
        logger.warning("未抓取到任何新闻，请检查站点选择器或网络连接。")
        return

    logger.info("共抓取 %d 条新闻", len(raw_items))

    analyzer = SentimentAnalyzer()
    model_version = analyzer.client.model_version
    mode = settings.sentiment_mode

    # ---- 分析前筛选：跳过已分析 URL，避免重复调用 LLM（C-2）----
    to_analyze = raw_items
    skipped_cache = 0
    if _HAS_DB:
        try:
            to_analyze = db_layer.select_unanalyzed(raw_items, model_version, mode)
            skipped_cache = len(raw_items) - len(to_analyze)
            logger.info(
                "缓存命中 %d 条（已分析，跳过 LLM）；待分析 %d 条",
                skipped_cache, len(to_analyze),
            )
        except Exception as exc:
            logger.warning("分析前筛选失败，将全量分析：%s", exc)
            to_analyze = raw_items
    else:
        logger.warning("未安装 SQLAlchemy，跳过缓存筛选与落库，仅输出文件。")

    analyzed_pairs: list = []
    if to_analyze:
        logger.info("开始 LLM 情感分析（%d 条）...", len(to_analyze))
        analyzed_pairs = await analyzer.analyze_many(to_analyze)
        logger.info("分析完成：%d 条", len(analyzed_pairs))
    else:
        logger.info("全部新闻已分析，无需调用 LLM。")

    # ---- 落库（需求 4：批量幂等写入）----
    db_stats = None
    if _HAS_DB and analyzed_pairs:
        try:
            db_stats = db_layer.persist(analyzed_pairs, mode)
            logger.info(
                "落库完成：新闻新增 %d / 复用 %d；情感新增 %d / 更新 %d；失败 %d",
                db_stats["news_inserted"], db_stats["news_existing"],
                db_stats["sentiment_inserted"], db_stats["sentiment_updated"],
                db_stats["failed"],
            )
        except Exception as exc:
            logger.error("落库失败：%s", exc)

    # ---- 文件输出（次级产物，便于人工抽查）----
    results = _build_analyzed(analyzed_pairs)
    if results:
        written = save_results(
            results,
            output_dir=settings.output_dir,
            write_json=settings.output_json,
            write_csv=settings.output_csv,
        )
        for fmt, path in written.items():
            logger.info("%s 输出: %s", fmt.upper(), os.path.abspath(path))

    # ---- 进度统计（需求 5：可观测性）----
    pos = sum(1 for r in results if r.sentiment_label == "positive")
    neg = sum(1 for r in results if r.sentiment_label == "negative")
    neu = sum(1 for r in results if r.sentiment_label == "neutral")
    fail = sum(1 for r in results if r.confidence == 0.0 and (r.key_sentence or "").startswith(("LLM", "分析", "模型", "异常")))
    logger.info(
        "本轮汇总：抓取 %d | 缓存跳过 %d | 新分析 %d | 正向 %d / 负向 %d / 中性 %d | 疑似失败 %d | 耗时 %.1fs",
        len(raw_items), skipped_cache, len(results), pos, neg, neu, fail, time.time() - t0,
    )
    print(f"[INFO] 正向: {pos} | 负向: {neg} | 中性: {neu}")


if __name__ == "__main__":
    asyncio.run(main())
