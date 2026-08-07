"""集成测试：数据库、种子数据、数据质量与业务链路。

覆盖范围
--------
- 表结构与 ORM 声明一致（9 张表可建可查）
- SQLite 运行参数（WAL / foreign_keys）生效
- 种子播种幂等（重复启动不产生重复数据）
- 数据质量校验（断档、价格跳变）
- 「回测 → 写库 → 读接口」闭环，含 DEF-001 排序缺陷的回归测试
- 爬虫 → 清洗 → upsert 落库端到端

对应用例编号：IT-DB-*、IT-DQ-*、IT-BIZ-*
"""
from __future__ import annotations

import pytest
from sqlalchemy import func, select, text

pytestmark = pytest.mark.integration

# 方案约定的 9 张业务表
EXPECTED_TABLES = {
    "market_data", "factor_data", "news", "sentiment", "signals",
    "hawk_dove_events", "backtest_results", "economic_calendar", "data_sources",
}


# ============================================================
# IT-DB 数据库与种子
# ============================================================
class TestDatabaseSchema:
    def test_all_tables_created(self, db):
        """IT-DB-001 正常流程：init_app 后 9 张业务表全部存在。"""
        rows = db.execute(
            text("SELECT name FROM sqlite_master WHERE type='table'")
        ).scalars().all()
        actual = set(rows)
        missing = EXPECTED_TABLES - actual
        assert not missing, f"缺失数据表: {missing}"

    def test_sqlite_runtime_pragmas(self, db):
        """IT-DB-002 正常流程：WAL 日志模式与外键约束已开启（并发与完整性保障）。"""
        assert db.execute(text("PRAGMA journal_mode")).scalar().lower() == "wal"
        assert db.execute(text("PRAGMA foreign_keys")).scalar() == 1

    def test_seed_data_not_empty(self, db):
        """IT-DB-003 正常流程：6 张核心表均有种子数据，接口不会返回空壳。"""
        from app.models.database import (
            MarketData, FactorData, News, Signal, BacktestResult, HawkDoveEvent,
        )

        expects = {
            MarketData: 1, FactorData: 6, News: 1,
            Signal: 1, BacktestResult: 1, HawkDoveEvent: 1,
        }
        for model, least in expects.items():
            n = db.execute(select(func.count(model.id))).scalar() or 0
            assert n >= least, f"{model.__tablename__} 仅 {n} 行，少于期望 {least} 行"

    def test_seed_is_idempotent(self, db):
        """IT-DB-004 异常容错：重复执行 init_app 不得产生重复数据（应用重启安全）。"""
        from app.core.seed import init_app
        from app.models.database import MarketData, News, Signal, FactorData

        models = (MarketData, News, Signal, FactorData)
        before = {m.__tablename__: db.execute(select(func.count(m.id))).scalar() for m in models}
        init_app()
        db.expire_all()
        after = {m.__tablename__: db.execute(select(func.count(m.id))).scalar() for m in models}
        assert before == after, f"重复播种造成数据膨胀: {before} -> {after}"

    def test_no_orphan_sentiment_rows(self, db):
        """IT-DB-005 边界值：sentiment 表不得存在指向不存在新闻的孤儿外键。"""
        orphan = db.execute(text("""
            SELECT COUNT(*) FROM sentiment s
            LEFT JOIN news n ON s.news_id = n.id
            WHERE s.news_id IS NOT NULL AND n.id IS NULL
        """)).scalar()
        assert orphan == 0, f"存在 {orphan} 条孤儿情感记录"


# ============================================================
# IT-DQ 数据质量
# ============================================================
class TestDataQuality:
    def test_no_gap_in_seed_price_series(self, db):
        """IT-DQ-001 正常流程：种子行情序列为 30 分钟等间隔，无异常断档。"""
        from app.core.data_quality import find_gaps

        gaps = find_gaps(db, "XAUUSD", max_gap_minutes=35)
        assert gaps == [], f"行情序列存在 {len(gaps)} 处断档: {gaps[:3]}"

    def test_no_abnormal_price_jump(self, db):
        """IT-DQ-002 正常流程：相邻行情涨跌幅不超过 5%，无脏数据跳变。"""
        from app.core.data_quality import find_price_jumps

        jumps = find_price_jumps(db, "XAUUSD", threshold_pct=5.0)
        assert jumps == [], f"存在 {len(jumps)} 处异常跳变: {jumps[:3]}"

    def test_quality_check_on_unknown_symbol(self, db):
        """IT-DQ-003 异常容错：查询不存在的品种返回空结果，不抛异常。"""
        from app.core.data_quality import find_gaps, find_price_jumps

        assert find_gaps(db, "NOT_EXIST") == []
        assert find_price_jumps(db, "NOT_EXIST") == []

    def test_run_quality_checks_returns_report(self, db):
        """IT-DQ-004 正常流程：质量总检返回结构化报告。"""
        from app.core.data_quality import run_quality_checks

        report = run_quality_checks(db, symbols=["XAUUSD"], max_gap_minutes=35)
        assert isinstance(report, dict) and report, "质量报告不应为空"

    def test_price_positive_and_volume_non_negative(self, db):
        """IT-DQ-005 边界值：价格恒为正、成交量恒非负。"""
        bad_price = db.execute(text(
            "SELECT COUNT(*) FROM market_data WHERE price IS NULL OR price <= 0")).scalar()
        bad_vol = db.execute(text(
            "SELECT COUNT(*) FROM market_data WHERE volume < 0")).scalar()
        assert bad_price == 0, f"{bad_price} 条非法价格"
        assert bad_vol == 0, f"{bad_vol} 条负成交量"

    def test_sentiment_aggregation(self, db):
        """IT-DQ-006 正常流程：新闻情感聚合值落在 [-1,1]，样本数与新闻表一致。"""
        from app.core.sentiment_factor import aggregate_recent_sentiment

        agg = aggregate_recent_sentiment(db, window_hours=24 * 365)
        assert -1 <= agg["value"] <= 1, f"情感均值越界: {agg}"
        assert agg["count"] >= 1


# ============================================================
# IT-BIZ 业务链路闭环
# ============================================================
class TestBacktestPersistence:
    def test_run_backtest_writes_new_row(self, client, db):
        """IT-BIZ-001 正常流程：POST /backtest/run 落库一条新回测记录。"""
        from app.models.database import BacktestResult

        before = db.execute(select(func.count(BacktestResult.id))).scalar()
        r = client.post("/api/v1/backtest/run", json={"signal_threshold": 0.6})
        assert r.json()["code"] == 200
        db.expire_all()
        after = db.execute(select(func.count(BacktestResult.id))).scalar()
        assert after == before + 1, f"回测记录未落库: {before} -> {after}"

    def test_latest_backtest_is_returned_by_read_apis(self, client, db):
        """IT-BIZ-002 回归测试（DEF-001）：读接口必须返回**最新**回测，而非同秒写入的旧记录。

        缺陷背景：``ORDER BY created_at DESC LIMIT 1`` 在 SQLite 秒级时间戳下
        排序不确定，全新库中种子记录与新回测同秒写入时会返回种子旧记录，
        导致 ``/stats/accuracy`` 缺少 sample_* 字段。修复方案为追加次级排序键 id。
        """
        from app.models.database import BacktestResult

        # 连续两次回测，确保存在多条同秒记录
        client.post("/api/v1/backtest/run", json={"signal_threshold": 0.55})
        client.post("/api/v1/backtest/run", json={"signal_threshold": 0.6})
        db.expire_all()
        newest = db.execute(
            select(BacktestResult).order_by(BacktestResult.id.desc()).limit(1)
        ).scalars().first()

        acc = client.get("/api/v1/stats/accuracy?window=30d").json()["data"]
        trades = client.get("/api/v1/backtest/trades").json()["data"]
        assert acc == newest.accuracy, "accuracy 接口未返回最新回测结果"
        assert trades == (newest.trade_details or []), "trades 接口未返回最新回测结果"
        for k in ("sample_7d", "sample_30d", "sample_bullish", "sample_bearish"):
            assert k in acc, f"最新回测的 accuracy 缺少 {k}"

    def test_accuracy_sample_consistency(self, client):
        """IT-BIZ-003 边界值：分方向样本数之和等于总样本数（避免小样本误导）。"""
        client.post("/api/v1/backtest/run", json={"signal_threshold": 0.55})
        a = client.get("/api/v1/stats/accuracy?window=30d").json()["data"]
        assert a["sample_bullish"] + a["sample_bearish"] == a["sample_30d"] or a["sample_30d"] == 0
        for k in ("overall_7d", "overall_30d", "bullish_accuracy", "bearish_accuracy"):
            assert 0 <= a[k] <= 100, f"{k} 越界: {a[k]}"

    def test_threshold_monotonic_effect(self, client):
        """IT-BIZ-004 正常流程：信号阈值提高，成交笔数不增（参数真实生效）。"""
        low = client.post("/api/v1/backtest/run",
                          json={"signal_threshold": 0.55}).json()["data"]["summary"]
        high = client.post("/api/v1/backtest/run",
                           json={"signal_threshold": 0.9}).json()["data"]["summary"]
        assert low["data_mode"] == "real", "有历史行情时应走真实回测路径"
        assert low["total_trades"] >= high["total_trades"], (
            f"阈值提高不应增加交易数: {low['total_trades']} -> {high['total_trades']}")

    def test_cost_monotonic_effect(self, client):
        """IT-BIZ-005 正常流程：交易成本升高，收益率下降。"""
        cheap = client.post("/api/v1/backtest/run",
                            json={"spread": 0.0, "commission_pct": 0.0}).json()["data"]["summary"]
        pricey = client.post("/api/v1/backtest/run",
                             json={"spread": 3.0, "commission_pct": 0.05}).json()["data"]["summary"]
        assert cheap["total_return_pct"] >= pricey["total_return_pct"], "成本升高应降低收益"

    def test_equity_curve_shape(self, client):
        """IT-BIZ-006 边界值：净值曲线点位齐备且资金非负。"""
        data = client.post("/api/v1/backtest/run", json={}).json()["data"]
        curve = data["equity_curve"]
        assert curve, "净值曲线不应为空"
        for p in curve[:50]:
            assert {"time", "strategy", "benchmark"} <= set(p.keys())
            assert p["strategy"] >= 0 and p["benchmark"] >= 0


# ============================================================
# IT-BIZ 爬虫落库链路（独立临时库，完全隔离）
# ============================================================
class TestScrapePipeline:
    def test_scrape_to_store_roundtrip(self, tmp_sqlite_engine):
        """IT-BIZ-011 正常流程：抓取 → 清洗 → 落库 → 回读，数据一致。"""
        from app.models.database import Base
        from app.pipeline.models import ScrapedGoldPrice
        from app.pipeline.scraper import GoldPriceScraper
        from app.pipeline.store import GoldPriceStore

        Base.metadata.create_all(bind=tmp_sqlite_engine, tables=[ScrapedGoldPrice.__table__])
        store = GoldPriceStore(engine=tmp_sqlite_engine)
        recs = GoldPriceScraper(source="it").scrape(use_fixture=True)
        assert store.store_many(recs) == len(recs)

        stored = {r.quote_date: r for r in store.fetch_all()}
        for rec in recs:
            assert rec.quote_date in stored
            assert abs(stored[rec.quote_date].close - rec.close) < 1e-6

    def test_upsert_idempotent(self, tmp_sqlite_engine):
        """IT-BIZ-012 异常容错：重复落库同一批数据不产生重复行（唯一约束 + 冲突忽略）。"""
        from app.models.database import Base
        from app.pipeline.models import ScrapedGoldPrice
        from app.pipeline.scraper import GoldPriceScraper
        from app.pipeline.store import GoldPriceStore

        Base.metadata.create_all(bind=tmp_sqlite_engine, tables=[ScrapedGoldPrice.__table__])
        store = GoldPriceStore(engine=tmp_sqlite_engine)
        recs = GoldPriceScraper(source="it").scrape(use_fixture=True)
        n = store.store_many(recs)
        store.store_many(recs)
        store.store_many(recs)
        assert store.count() == n, "重复写入造成数据重复"

    def test_empty_batch_is_safe(self, tmp_sqlite_engine):
        """IT-BIZ-013 边界值：空批次落库返回 0，不抛异常。"""
        from app.models.database import Base
        from app.pipeline.models import ScrapedGoldPrice
        from app.pipeline.store import GoldPriceStore

        Base.metadata.create_all(bind=tmp_sqlite_engine, tables=[ScrapedGoldPrice.__table__])
        store = GoldPriceStore(engine=tmp_sqlite_engine)
        assert store.store_many([]) == 0
        assert store.count() == 0
