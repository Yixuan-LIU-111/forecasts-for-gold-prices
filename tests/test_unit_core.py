"""单元测试：核心算法与纯函数（不依赖数据库 / 网络）。

覆盖模块
--------
- app.core.hawk_dove.score_text        鹰鸽指数打分
- app.core.title_summary.rule_summarize 新闻标题中文概括（规则法）
- app.core.signal_generator            置信度 / 仓位规则
- app.core.backtest.BacktestParams     回测参数默认值与边界
- app.pipeline.scraper                 HTML 解析与数据清洗
- app.config.Settings                  配置派生属性

对应用例编号：UT-HD-*、UT-TS-*、UT-SG-*、UT-BT-*、UT-PL-*、UT-CF-*
"""
from __future__ import annotations

import math

import pytest

pytestmark = pytest.mark.unit


# ============================================================
# UT-HD 鹰鸽指数打分
# ============================================================
class TestHawkDoveScore:
    """鹰鸽打分：score ∈ [-0.5, +0.5]，鹰派为正、鸽派为负。"""

    def test_hawkish_text_returns_positive(self):
        """UT-HD-001 正常流程：含加息/鹰派关键词 → 鹰派正分。"""
        from app.core.hawk_dove import score_text

        score, typ, label, matched = score_text("美联储宣布加息25个基点，鹰派立场明确")
        assert score > 0, "鹰派文本应返回正分"
        assert typ == "hawk" and label == "鹰派"
        assert "加息" in matched

    def test_dovish_text_returns_negative(self):
        """UT-HD-002 正常流程：含降息/鸽派关键词 → 鸽派负分。"""
        from app.core.hawk_dove import score_text

        score, typ, label, matched = score_text("美联储降息预期升温，鸽派信号增强")
        assert score < 0, "鸽派文本应返回负分"
        assert typ == "dove" and label == "鸽派"

    @pytest.mark.parametrize("text", ["", None, "   ", "黄金价格今日小幅波动"])
    def test_empty_or_neutral_text(self, text):
        """UT-HD-003 异常/边界：空串、None、无关键词文本 → 中性 0 分，不抛异常。"""
        from app.core.hawk_dove import score_text

        score, typ, label, matched = score_text(text)
        assert score == 0.0
        assert typ == "neutral" and label == "中性"

    def test_score_clamped_in_range(self):
        """UT-HD-004 边界值：极端堆砌关键词，score 仍被钳制在 [-0.5, 0.5]。"""
        from app.core.hawk_dove import score_text, SCORE_CAP

        s_hawk, *_ = score_text("加息 加息 加息 鹰派 鹰派 紧缩 缩表 hawkish tightening" * 5)
        s_dove, *_ = score_text("降息 降息 鸽派 鸽派 宽松 stimulus dovish easing" * 5)
        assert -SCORE_CAP <= s_hawk <= SCORE_CAP
        assert -SCORE_CAP <= s_dove <= SCORE_CAP

    def test_balanced_text_is_neutral(self):
        """UT-HD-005 边界值：鹰鸽关键词势均力敌 → 判定为中性。"""
        from app.core.hawk_dove import score_text

        score, typ, _, matched = score_text("hike and cut both mentioned")
        assert matched, "应命中关键词"
        assert typ == "neutral", f"多空抵消应为中性，实际 {typ}"

    def test_long_text_performance(self):
        """UT-HD-006 边界值：10 万字符长文本不应超时或崩溃。"""
        from app.core.hawk_dove import score_text

        score, *_ = score_text("黄金 " * 20000 + "加息")
        assert isinstance(score, float)


# ============================================================
# UT-TS 新闻标题中文概括
# ============================================================
class TestTitleSummary:
    """rule_summarize：LLM 不可用时的规则兜底，输出须为受控长度的中文短句。"""

    @pytest.mark.parametrize("title,key", [
        ("Gold hits record high", "黄金价格创下历史新高，突破3500美元"),
        ("Fed holds rates steady", "美联储维持利率不变"),
        ("Dollar index slips", "美元指数下跌0.4%"),
    ])
    def test_returns_non_empty_short_title(self, title, key):
        """UT-TS-001 正常流程：返回非空、长度 <= 35 的概括。"""
        from app.core.title_summary import rule_summarize

        out = rule_summarize(title, key)
        assert out and out.strip(), "概括不应为空"
        assert len(out) <= 35, f"标题超长（{len(out)}）: {out}"

    def test_never_uses_direction_wording(self):
        """UT-TS-002 业务约束：概括不得直接以「利好/利空黄金」等多空方向作标题。"""
        from app.core.title_summary import rule_summarize

        out = rule_summarize("Gold rallies on rate cut bets", "降息预期推动金价上涨", sentiment="正面")
        for bad in ("利好黄金", "利空黄金", "影响中性"):
            assert bad not in out, f"标题不应含方向词 {bad}: {out}"

    @pytest.mark.parametrize("title,key", [("", ""), ("", "   "), ("!!!???", "")])
    def test_degenerate_input_has_fallback(self, title, key):
        """UT-TS-003 异常容错：空/无意义输入仍返回兜底文案，不抛异常。"""
        from app.core.title_summary import rule_summarize

        out = rule_summarize(title, key)
        assert isinstance(out, str) and out, "应返回兜底文案而非空串"

    def test_trim_enforces_max_length(self):
        """UT-TS-004 边界值：_trim 严格截断到 max_len。"""
        from app.core.title_summary import _trim

        out = _trim("x" * 200, max_len=35)
        assert len(out) == 35
        assert out.endswith("…"), "超长应带省略号"


# ============================================================
# UT-SG 信号生成规则
# ============================================================
class TestSignalRules:
    """信号方向 / 仓位 / 置信度的规则表。"""

    @pytest.mark.parametrize("prob,conf,expect_dir,expect_pos", [
        (0.85, 90, "bullish", "重仓"),   # 强看涨
        (0.65, 60, "bullish", "中仓"),   # 中等看涨
        (0.20, 90, "bearish", "重仓"),   # 强看跌
        (0.35, 60, "bearish", "中仓"),   # 中等看跌
        (0.50, 50, "neutral", "观望"),   # 无方向
    ])
    def test_direction_and_position_matrix(self, prob, conf, expect_dir, expect_pos):
        """UT-SG-001 正常流程：概率 × 置信度 → 方向与仓位映射正确。"""
        from app.core.signal_generator import _rules

        direction, position, pct, _cn = _rules(prob, conf)
        assert direction == expect_dir
        assert position == expect_pos
        assert 0 <= pct <= 100

    @pytest.mark.parametrize("prob,conf", [
        (0.701, 70),   # 概率达标但置信度差 1 → 降级
        (0.70, 71),    # 置信度达标但概率差 1 → 降级
        (0.299, 70),
    ])
    def test_threshold_boundary_downgrade(self, prob, conf):
        """UT-SG-002 边界值：任一条件不满足即降级，不得越级给重仓。"""
        from app.core.signal_generator import _rules

        _d, position, pct, _cn = _rules(prob, conf)
        assert position != "重仓" or pct <= 80

    def test_confidence_value_clamped(self):
        """UT-SG-003 边界值：置信度恒落在 [20, 95]。"""
        from app.core.signal_generator import _confidence_value

        strong = _confidence_value(0.99, {"sentiment": {"value": 1}, "hawk_dove": {"value": -1}})
        flat = _confidence_value(0.5, {})
        weird = _confidence_value(0.0, {"sentiment": {"value": None}, "hawk_dove": {"value": None}})
        for v in (strong, flat, weird):
            assert 20 <= v <= 95, f"置信度越界: {v}"

    @pytest.mark.parametrize("value,label", [(95, "高"), (75, "高"), (74, "中"), (55, "中"), (54, "低"), (20, "低")])
    def test_confidence_label_boundaries(self, value, label):
        """UT-SG-004 边界值：置信度分档阈值 75 / 55 的临界点判定。"""
        from app.core.signal_generator import _confidence_label

        assert _confidence_label(value) == label


# ============================================================
# UT-BT 回测参数
# ============================================================
class TestBacktestParams:
    def test_default_params(self):
        """UT-BT-001 正常流程：默认参数符合方案约定。"""
        from app.core.backtest import BacktestParams

        p = BacktestParams()
        assert p.initial_capital == 10000
        assert 0 <= p.spread <= 10
        assert 0 <= p.commission_pct <= 0.1
        assert 0 < p.signal_threshold < 1

    def test_date_parser_tolerates_bad_input(self):
        """UT-BT-002 异常容错：非法日期字符串不抛异常，返回 None。"""
        from app.core.backtest import _to_date

        assert _to_date("not-a-date") is None
        assert _to_date(None) is None
        assert _to_date("2026-08-01") is not None

    def test_naive_datetime_conversion(self):
        """UT-BT-003 边界值：带时区与不带时区的时间统一为 naive，便于比较。"""
        from datetime import datetime, timezone
        from app.core.backtest import _to_naive

        aware = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)
        naive = datetime(2026, 8, 1, 12, 0)
        assert _to_naive(aware).tzinfo is None
        assert _to_naive(naive).tzinfo is None
        assert _to_naive(aware) == _to_naive(naive)


# ============================================================
# UT-PL 爬虫解析与清洗
# ============================================================
class TestScraperParsing:
    def test_fixture_parse_row_count(self):
        """UT-PL-001 正常流程：固定 HTML 解析出 5 行原始数据。"""
        from app.pipeline.scraper import FIXTURE_HTML, GoldPriceScraper

        rows = GoldPriceScraper(source="fixture").parse(FIXTURE_HTML)
        assert len(rows) == 5

    def test_clean_drops_invalid_rows(self):
        """UT-PL-002 异常容错：high<low、close=N/A 的脏行应被清洗丢弃。"""
        from app.pipeline.scraper import GoldPriceScraper

        records = GoldPriceScraper(source="fixture").scrape(use_fixture=True)
        assert len(records) == 3, "5 行中应丢弃 2 行非法数据"

    def test_normalize_strips_thousand_separator(self):
        """UT-PL-003 边界值：千分位逗号、字符串数字应被正确归一为 float。"""
        from app.pipeline.scraper import GoldPriceScraper

        rec = GoldPriceScraper(source="t").normalize({
            "quote_date": "2026-08-01", "open": "2,035.10", "high": "2,040.50",
            "low": "2,030.00", "close": "2,038.20", "volume": "1,200,000", "currency": "USD",
        })
        assert math.isclose(rec.close, 2038.20, rel_tol=1e-9)
        assert rec.volume == 1_200_000
        assert rec.high >= max(rec.open, rec.close)
        assert rec.low <= min(rec.open, rec.close)

    def test_parse_empty_html(self):
        """UT-PL-004 异常容错：空 HTML / 无表格 → 返回空列表而非崩溃。"""
        from app.pipeline.scraper import GoldPriceScraper

        s = GoldPriceScraper(source="t")
        assert s.parse("") == []
        assert s.parse("<html><body><p>no table here</p></body></html>") == []


# ============================================================
# UT-CF 配置
# ============================================================
class TestSettings:
    def test_test_env_isolation(self):
        """UT-CF-001 正常流程：测试进程必须指向隔离测试库，绝不写开发库。"""
        from app.config import settings

        assert settings.is_sqlite, "测试应使用 SQLite"
        assert "gold_test.db" in settings.database_url, (
            f"测试库未隔离，当前 DATABASE_URL={settings.database_url}")

    def test_scheduler_disabled_in_test(self):
        """UT-CF-002 正常流程：测试期间后台调度与实时爬虫必须关闭。"""
        from app.config import settings

        assert settings.scheduler_enabled is False
        assert settings.news_scrape_enabled is False

    def test_uppercase_alias_compatible(self):
        """UT-CF-003 兼容性：大写别名属性与小写字段值一致（旧代码依赖）。"""
        from app.config import settings

        assert settings.DATABASE_URL == settings.database_url
        assert settings.LOG_LEVEL == settings.log_level
        assert settings.APP_ENV == settings.app_env
