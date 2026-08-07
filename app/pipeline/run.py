"""
端到端编排：抓取 -> 清洗 -> 落库 -> 汇总。

用法：
    # 使用内置样本（离线可跑，无需网络）
    PYTHONPATH=. python -m app.pipeline.run

    # 抓取真实页面
    PYTHONPATH=. python -m app.pipeline.run --url https://<your-gold-price-page>
"""
from __future__ import annotations

import argparse
import logging

from app.models.database import init_db
from app.pipeline.scraper import GoldPriceScraper
from app.pipeline.store import GoldPriceStore

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("pipeline.run")


def run_pipeline(
    url: str | None = None,
    use_fixture: bool = True,
    source: str = "gold_scraper",
) -> int:
    """执行一次「抓取 -> 清洗 -> 落库」并返回写入行数。"""
    init_db()  # 确保全部表（含 scraped_gold_prices）存在
    scraper = GoldPriceScraper(source=source)
    records = scraper.scrape(url=url, use_fixture=use_fixture)
    store = GoldPriceStore()
    n = store.store_many(records, source=source)
    logger.info("落库完成：尝试写入 %d 行，当前表内共 %d 行", n, store.count(source=source))
    return n


def main() -> None:
    p = argparse.ArgumentParser(description="黄金价格页面爬虫 -> 落库")
    p.add_argument("--url", default=None, help="目标页面 URL；省略则使用内置样本（离线）")
    p.add_argument("--source", default="gold_scraper", help="数据来源标识")
    args = p.parse_args()
    run_pipeline(url=args.url, use_fixture=args.url is None, source=args.source)


if __name__ == "__main__":
    main()
