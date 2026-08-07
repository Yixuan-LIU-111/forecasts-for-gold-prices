"""
黄金价格「页面爬虫 -> 数据落库」自动化测试。

覆盖三个维度：
- 字段正确性：类型、价格区间、OHLC 一致性
- 完整性：必填非空、成交量非负
- 一致性：写入后往返一致、upsert 幂等（不重复）、来源过滤

运行（仓库根目录）：
    PYTHONPATH=. python -m unittest tests.test_pipeline -v
    PYTHONPATH=. python tests/test_pipeline.py
"""
import os
import sys
import tempfile
import unittest
from datetime import date

from sqlalchemy import create_engine, Engine, func, select
from sqlalchemy.orm import Session

# 允许直接 `python tests/test_pipeline.py` 运行：把仓库根加入路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.models.database import Base  # noqa: E402
from app.pipeline.models import ScrapedGoldPrice  # noqa: E402
from app.pipeline.scraper import FIXTURE_HTML, GoldPriceScraper  # noqa: E402
from app.pipeline.store import GoldPriceStore  # noqa: E402


def make_temp_engine() -> Engine:
    """创建独立临时 SQLite 库并仅建 scraped_gold_prices 表，隔离测试。"""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.remove(path)
    eng = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(bind=eng, tables=[ScrapedGoldPrice.__table__])
    return eng


class TestScraperParse(unittest.TestCase):
    """解析层：表格解析与清洗丢弃非法行。"""

    def setUp(self) -> None:
        self.scraper = GoldPriceScraper(source="fixture")

    def test_parse_row_count(self):
        rows = self.scraper.parse(FIXTURE_HTML)
        self.assertEqual(len(rows), 5)

    def test_parse_column_mapping(self):
        rows = self.scraper.parse(FIXTURE_HTML)
        for col in ("quote_date", "open", "high", "low", "close", "volume", "currency"):
            self.assertIn(col, rows[0], f"缺少列 {col}")

    def test_clean_drops_invalid(self):
        records = self.scraper.scrape(use_fixture=True)
        # 5 行中 2 行非法（high<low 的 08-03、close=N/A 的 08-05），剩 3 行有效
        self.assertEqual(len(records), 3)
        dates = {r.quote_date for r in records}
        self.assertIn(date(2026, 8, 1), dates)
        self.assertIn(date(2026, 8, 2), dates)
        self.assertIn(date(2026, 8, 4), dates)
        self.assertNotIn(date(2026, 8, 3), dates)
        self.assertNotIn(date(2026, 8, 5), dates)


class TestFieldCorrectness(unittest.TestCase):
    """字段正确性：类型、价格区间、OHLC 一致性。"""

    def setUp(self) -> None:
        self.engine = make_temp_engine()
        self.store = GoldPriceStore(engine=self.engine)
        self.rec = GoldPriceScraper(source="t").normalize({
            "quote_date": "2026-08-01", "open": "2,035.10", "high": "2,040.50",
            "low": "2,030.00", "close": "2,038.20", "volume": "1,200,000", "currency": "USD",
        })

    def tearDown(self) -> None:
        self.engine.dispose()

    def test_types(self):
        self.assertIsInstance(self.rec.quote_date, date)
        self.assertIsInstance(self.rec.close, float)
        self.assertIsInstance(self.rec.currency, str)

    def test_price_range(self):
        self.assertTrue(1.0 <= self.rec.close <= 100_000.0)

    def test_ohlc_consistency(self):
        self.assertGreaterEqual(self.rec.high, max(self.rec.open, self.rec.close))
        self.assertLessEqual(self.rec.low, min(self.rec.open, self.rec.close))


class TestIntegrity(unittest.TestCase):
    """完整性：必填非空、成交量非负。"""

    def setUp(self) -> None:
        self.engine = make_temp_engine()
        self.store = GoldPriceStore(engine=self.engine)
        self.records = GoldPriceScraper(source="t").scrape(use_fixture=True)
        self.store.store_many(self.records)

    def tearDown(self) -> None:
        self.engine.dispose()

    def test_no_null_close(self):
        with Session(self.engine) as db:
            nulls = db.scalar(
                select(func.count()).select_from(ScrapedGoldPrice)
                .where(ScrapedGoldPrice.close.is_(None))
            )
        self.assertEqual(nulls, 0)

    def test_required_columns_present(self):
        with Session(self.engine) as db:
            row = db.scalars(select(ScrapedGoldPrice)).first()
        self.assertIsNotNone(row.source)
        self.assertIsNotNone(row.symbol)
        self.assertIsNotNone(row.quote_date)
        self.assertIsNotNone(row.currency)

    def test_volume_non_negative(self):
        with Session(self.engine) as db:
            neg = db.scalar(
                select(func.count()).select_from(ScrapedGoldPrice)
                .where(ScrapedGoldPrice.volume < 0)
            )
        self.assertEqual(neg, 0)


class TestConsistency(unittest.TestCase):
    """一致性：往返一致、upsert 幂等、来源过滤。"""

    def setUp(self) -> None:
        self.engine = make_temp_engine()
        self.store = GoldPriceStore(engine=self.engine)
        self.records = GoldPriceScraper(source="t").scrape(use_fixture=True)

    def tearDown(self) -> None:
        self.engine.dispose()

    def test_roundtrip(self):
        self.store.store_many(self.records)
        stored = {r.quote_date: r for r in self.store.fetch_all()}
        for rec in self.records:
            self.assertIn(rec.quote_date, stored)
            s = stored[rec.quote_date]
            self.assertAlmostEqual(s.close, rec.close, places=4)
            if rec.open is not None:
                self.assertAlmostEqual(s.open, rec.open, places=4)

    def test_upsert_idempotent(self):
        n1 = self.store.store_many(self.records)
        self.store.store_many(self.records)  # 再次写入完全相同的数据
        self.assertEqual(self.store.count(), n1)  # 唯一约束 + ON CONFLICT DO NOTHING -> 不重复

    def test_source_filter(self):
        self.store.store_many(self.records, source="S1")
        self.assertEqual(self.store.count(source="S1"), len(self.records))
        self.assertEqual(self.store.count(source="OTHER"), 0)


class TestEndToEnd(unittest.TestCase):
    """端到端：抓取到落库整链路。"""

    def setUp(self) -> None:
        self.engine = make_temp_engine()
        self.store = GoldPriceStore(engine=self.engine)

    def tearDown(self) -> None:
        self.engine.dispose()

    def test_scrape_to_store(self):
        recs = GoldPriceScraper(source="e2e").scrape(use_fixture=True)
        n = self.store.store_many(recs)
        self.assertEqual(n, len(recs))
        self.assertEqual(self.store.count(), len(recs))


if __name__ == "__main__":
    unittest.main(verbosity=2)
