"""
历史数据预加载脚本（B-8）：回填约 3 个月市场数据 + 新闻，作为里程碑 M1 检查点。

串联：
- YFinanceCollector.collect_and_store(db)  → market_data（B-4）
- NewsAPICollector.collect_and_store(db)   → news（B-5 + B-6 去重）

运行：
    cd "/Users/echo/Desktop/forecasts for gold prices"
    python -m app.core.bootstrap_data

⚠️ 风险 R2（分钟级历史长度限制）：
    yfinance 的分钟级历史受额度限制（1m 仅 ~7 天、5m ~60 天）。YFinanceCollector
    默认 5m / 60d，因此本脚本实际回填约 60 天分钟级行情，而非完整 3 个月。
    完整 3 个月预加载需在 Stage 0（D-1/D-2）决策中补充历史数据源（见差距分析文档）。
"""
from __future__ import annotations

import asyncio
import logging

from app.core.data_collector import YFinanceCollector
from app.core.news_collector import NewsAPICollector
from app.models.database import SessionLocal, init_db

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("bootstrap_data")


async def bootstrap(db) -> dict:
    """执行预加载，返回各环节落库统计。"""
    market = YFinanceCollector().collect_and_store(db)
    log.info("market_data 落库完成: %s 行", market)

    news = await NewsAPICollector().collect_and_store(db)
    log.info(
        "news 落库: inserted=%s skipped_url=%s skipped_title=%s",
        news.get("inserted"), news.get("skipped_url"), news.get("skipped_title"),
    )
    return {"market": market, "news": news}


def main() -> None:
    log.info("确保数据库表结构存在（init_db）...")
    init_db()

    db = SessionLocal()
    try:
        summary = asyncio.run(bootstrap(db))
        log.info("预加载完成: %s", summary)
    finally:
        db.close()


if __name__ == "__main__":
    main()
