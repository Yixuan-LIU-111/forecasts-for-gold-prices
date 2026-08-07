"""
新闻采集器：封装 news_scraper_llm 现有抓取器，将结果写入 news 表，并做去重（B-5 + B-6）。

对齐 项目方案V1.0：
- §11.1：DataCollector 接口 / NewsAPICollector 命名
- §8.2：news 表结构（url TEXT UNIQUE 用于去重、published_at TIMESTAMPTZ NOT NULL）
- §8.3：新闻去重 = URL 精确匹配 + 标题相似度 > 0.8 判定为重复

设计要点：
- B-5：复用 news_scraper_llm 的 ScrapingEngine + 4 站点抓取器，结果持久化到 news 表
- B-6：两层去重
    1) URL 精确匹配：news.url 为 UNIQUE，先查后插保证幂等（重复 URL 直接跳过）
    2) 标题相似度 > 0.8：与近 30 天已存新闻标题比较，命中则跳过
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Sequence

import pandas as pd
from sqlalchemy import select

from app.core.data_collector import DataCollector
from app.core.title_summary import summarize_title
from app.models.database import SessionLocal
from app.models.tables import News

# 仓库根目录（与 news_scraper_llm 同级），保证可从任意工作目录导入现有爬虫
_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# 标题相似度阈值（§8.3：> 0.8 判定重复）
TITLE_SIMILARITY_THRESHOLD = 0.8
# 标题相似度比对窗口（仅与近 N 天的新闻标题比较，控制比较规模）
TITLE_DEDUP_WINDOW_DAYS = 30


def _title_similarity(a: str, b: str) -> float:
    """标题相似度 0~1；优先 rapidfuzz（分词无关比率），缺失则回退 difflib。"""
    a, b = (a or "").strip(), (b or "").strip()
    if not a or not b:
        return 0.0
    try:
        from rapidfuzz.fuzz import ratio
        return ratio(a, b) / 100.0
    except Exception:
        import difflib
        return difflib.SequenceMatcher(None, a, b).ratio()


def _parse_published_at(raw) -> datetime:
    """将 RawNewsItem 解析为带时区的 TIMESTAMPTZ；失败/缺失则回退 scraped_at / now()。"""
    val = getattr(raw, "published_at", None)
    if isinstance(val, datetime):
        return val if val.tzinfo else val.replace(tzinfo=timezone.utc)
    if isinstance(val, str) and val.strip():
        try:
            from dateutil import parser as _dp
            dt = _dp.parse(val)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except Exception:
            pass
    fallback = getattr(raw, "scraped_at", None) or datetime.now(timezone.utc)
    return fallback if fallback.tzinfo else fallback.replace(tzinfo=timezone.utc)


class NewsAPICollector(DataCollector):
    """新闻采集器（§11.1 命名）。fetch 抓取→DataFrame；store 去重落库。"""

    async def fetch(self) -> pd.DataFrame:
        """抓取 4 站点新闻，返回统一列 DataFrame。"""
        items = await self.fetch_raw()
        return pd.DataFrame([
            {
                "source": it.source,
                "title": it.title,
                "url": it.url,
                "published_at": it.published_at,
                "summary": it.summary,
                "category": it.category,
            }
            for it in items
        ])

    async def fetch_raw(self) -> list:
        """抓取并返回原始 RawNewsItem 列表（供 store / 情感分析使用）。

        惰性导入 news_scraper_llm，避免无 Playwright / langchain 依赖时模块导入即崩溃。
        """
        from news_scraper_llm.scrapers import (
            APNewsScraper,
            CNNScraper,
            FedScraper,
            WhiteHouseScraper,
        )
        from news_scraper_llm.scrapers.engine import ScrapingEngine
        from news_scraper_llm.config import settings

        engine = ScrapingEngine()
        engine.add(FedScraper(max_items=settings.max_items_per_site))
        engine.add(WhiteHouseScraper(max_items=settings.max_items_per_site))
        engine.add(APNewsScraper(max_items=settings.max_items_per_site))
        engine.add(CNNScraper(max_items=settings.max_items_per_site))
        return await engine.run()

    # ---------------- B-6 去重 ----------------

    @staticmethod
    def _title_already_exists(db, title: str) -> bool:
        """近 TITLE_DEDUP_WINDOW_DAYS 天内是否存在标题相似度 > 阈值的记录。"""
        since = datetime.now(timezone.utc) - timedelta(days=TITLE_DEDUP_WINDOW_DAYS)
        stmt = select(News.title).where(News.published_at >= since)
        existing = db.execute(stmt).scalars().all()
        return any(
            _title_similarity(title, t) > TITLE_SIMILARITY_THRESHOLD
            for t in existing
        )

    def _resolve_existing_url(self, db, url: str) -> int | None:
        """返回该 URL 已存在的新闻 id（用于去重计数与情感关联）；不存在返回 None。"""
        return db.execute(
            select(News.id).where(News.url == url)
        ).scalar_one_or_none()

    def store(self, db, items: Sequence) -> dict:
        """去重后写入 news 表（B-5 + B-6）。

        返回：
            {
              "inserted": int,          # 新插入条数
              "skipped_url": int,       # 因 URL 重复跳过
              "skipped_title": int,     # 因标题相似度 > 0.8 跳过
              "links": [                # 每条输入对应的 news_id（跳过时为 None）
                  (raw_item, news_id_or_None), ...
              ],
            }
        links 供下游 C-1 情感落库时按 news_id 关联使用。
        """
        inserted = skipped_url = skipped_title = 0
        links: list[tuple[object, int | None]] = []

        for raw in items:
            url = (getattr(raw, "url", None) or "").strip() or None
            title = (getattr(raw, "title", None) or "").strip()

            # 1) URL 精确去重（news.url UNIQUE，幂等）
            if url:
                existing_id = self._resolve_existing_url(db, url)
                if existing_id is not None:
                    skipped_url += 1
                    links.append((raw, existing_id))
                    continue

            # 2) 标题相似度 > 0.8 去重
            if title and self._title_already_exists(db, title):
                skipped_title += 1
                links.append((raw, None))
                continue

            # 3) 插入
            title_zh = summarize_title(title or "(无标题)", getattr(raw, "summary", None) or "")
            row = News(
                title=title or "(无标题)",
                title_zh=title_zh,
                content=getattr(raw, "summary", None),
                source=getattr(raw, "source", None),
                url=url,
                published_at=_parse_published_at(raw),
            )
            db.add(row)
            db.flush()  # 拿到自增 id，供下游情感关联
            inserted += 1
            links.append((raw, row.id))

        db.commit()
        return {
            "inserted": inserted,
            "skipped_url": skipped_url,
            "skipped_title": skipped_title,
            "links": links,
        }

    async def collect_and_store(self, db=None) -> dict:
        """抓取并落库；db 为空时新建并自管 Session。"""
        own = db is None
        session = db or SessionLocal()
        try:
            raw = await self.fetch_raw()
            return self.store(session, raw)
        finally:
            if own:
                session.close()
