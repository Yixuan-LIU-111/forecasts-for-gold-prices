"""API 契约一致性测试。

校验 12 个端点响应结构与 demo_data 等价，确保 DEMO/LIVE 模式无缝切换。
运行：pytest tests/test_api_contract.py -v
"""
import json

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.config import DEMO_DATA_DIR
from app.core.seed import init_app

# 显式初始化数据库 + 播种 demo_data。
# 不依赖 TestClient 的 lifespan（Starlette 0.36+ 未进入 with 上下文时不触发 startup），
# 保证无论测试客户端如何使用，DB 均已就绪。
init_app()

client = TestClient(app)


def _load(name: str):
    with open(DEMO_DATA_DIR / f"{name}.json", encoding="utf-8") as f:
        return json.load(f)


def _data(resp):
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["code"] == 200, body
    return body["data"]


def _assert_keys(actual, expected, path=""):
    """递归校验键集合一致（actual 须含 expected 所有键）。"""
    if isinstance(expected, dict):
        for k in expected:
            assert k in actual, f"缺少字段 {path}.{k}"
            _assert_keys(actual[k], expected[k], f"{path}.{k}")
    elif isinstance(expected, list) and expected:
        assert isinstance(actual, list) and actual, f"{path} 应为非空列表"
        _assert_keys(actual[0], expected[0], f"{path}[0]")


# ===== 1. latest signal =====
def test_signals_latest_matches_demo():
    expected = _load("signals")[0]
    actual = _data(client.get("/api/v1/signals/latest"))
    assert actual is not None
    _assert_keys(actual, expected)


# ===== 2. attribution =====
def test_signals_attribution():
    actual = _data(client.get("/api/v1/signals/attribution"))
    assert isinstance(actual, list)
    if actual:
        for k in ("factor", "value", "color", "detail"):
            assert k in actual[0]


# ===== 3. market price =====
def test_market_price_matches_demo():
    expected = _load("market")
    actual = _data(client.get("/api/v1/market/price?range_hours=4h"))
    _assert_keys(actual, expected)
    assert isinstance(actual["prices"], list)


# ===== 4. factors =====
def test_factors_matches_demo():
    expected = _load("factors")
    actual = _data(client.get("/api/v1/factors"))
    _assert_keys(actual, expected)
    assert len(actual["factors"]) == 6


# ===== 5. news =====
def test_news_matches_demo():
    expected = _load("news")[0]
    actual = _data(client.get("/api/v1/news?limit=20"))
    assert isinstance(actual, list)
    assert actual, "新闻不应为空"
    _assert_keys(actual[0], expected)


# ===== 6. backtest results =====
def test_backtest_results_matches_demo():
    expected = _load("backtest")
    actual = _data(client.get("/api/v1/backtest/results"))
    for k in ("summary", "accuracy", "equity_curve", "trade_details", "pnl_distribution", "hawk_dove_events"):
        assert k in actual, f"缺少 {k}"
    _assert_keys(actual["summary"], expected["summary"])
    _assert_keys(actual["accuracy"], expected["accuracy"])


# ===== 7. run backtest =====
def test_backtest_run():
    resp = client.post("/api/v1/backtest/run", json={})
    actual = _data(resp)
    assert "summary" in actual
    assert "trade_details" in actual


# ===== 8. accuracy =====
def test_accuracy():
    expected = _load("backtest")["accuracy"]
    actual = _data(client.get("/api/v1/stats/accuracy?window=7d"))
    _assert_keys(actual, expected)


# ===== 9. system status =====
def test_system_status():
    actual = _data(client.get("/api/v1/system/status"))
    for k in ("status", "data_collection", "llm_service", "db_connection",
              "model_loaded", "api_usage", "timestamp", "mode"):
        assert k in actual, f"缺少 {k}"


# ===== 10. hawk-dove events =====
def test_hawk_dove_events():
    expected = _load("backtest")["hawk_dove_events"][0]
    actual = _data(client.get("/api/v1/hawk-dove/events?days=7"))
    assert isinstance(actual, list)
    assert actual
    _assert_keys(actual[0], expected)


# ===== 11. pnl distribution =====
def test_pnl_distribution():
    expected = _load("backtest")["pnl_distribution"]
    actual = _data(client.get("/api/v1/backtest/pnl-distribution"))
    _assert_keys(actual, expected)
    assert isinstance(actual["bins"], list)
    assert isinstance(actual["counts"], list)


# ===== 12. trade details =====
def test_trade_details():
    expected = _load("backtest")["trade_details"][0]
    actual = _data(client.get("/api/v1/backtest/trades"))
    assert isinstance(actual, list)
    if actual:
        _assert_keys(actual[0], expected)


# ===== 13. system status 新增字段（前端页面优化 S2/S6）=====
def test_system_status_db_type_and_model_info():
    actual = _data(client.get("/api/v1/system/status"))
    assert actual["db_type"] in ("SQLite", "PostgreSQL", "Unknown")
    mi = actual["model_info"]
    assert mi is not None, "model_info 不应为空"
    for k in ("name", "status", "is_real_model", "demo_mode",
              "signal_threshold", "available_indicators"):
        assert k in mi, f"model_info 缺少 {k}"
    assert mi["status"] in ("loaded", "synthetic_baseline", "unavailable")
    assert isinstance(mi["available_indicators"], list)


# ===== 14. 数据源配置端点（前端页面优化 S5）=====
def test_system_data_sources():
    rows = _data(client.get("/api/v1/system/data-sources"))
    assert isinstance(rows, list) and rows, "数据源不应为空"
    for k in ("indicator_code", "indicator_name", "source_name",
              "update_frequency", "realtime"):
        assert k in rows[0], f"缺少 {k}"
    codes = {r["indicator_code"] for r in rows}
    # 建议 5 明确要求按真实情况列举（VIX 等）
    assert {"XAUUSD", "DXY", "VIX", "TIPS"} <= codes, f"缺少核心指标: {codes}"


# ===== 15. 回测参数校验（前端页面优化 S4）=====
@pytest.mark.parametrize("payload,keyword", [
    ({"initial_capital": 0}, "初始资金"),
    ({"spread": -1}, "点差"),
    ({"commission_pct": 5}, "手续费"),
    ({"signal_threshold": 1.5}, "信号阈值"),
])
def test_backtest_param_validation(payload, keyword):
    r = client.post("/api/v1/backtest/run", json=payload)
    body = r.json()
    assert body["code"] == 422, f"应返回 422，实际 {body['code']}"
    assert keyword in body["message"], body["message"]


# ===== 16. 回测参数真实生效（前端页面优化 S4）=====
def test_backtest_params_affect_result():
    low = client.post("/api/v1/backtest/run",
                      json={"signal_threshold": 0.55}).json()["data"]["summary"]
    high = client.post("/api/v1/backtest/run",
                       json={"signal_threshold": 0.9}).json()["data"]["summary"]
    assert low["data_mode"] == "real", "有历史行情时应走真实回测路径"
    assert low["total_trades"] > high["total_trades"], (
        f"阈值提高应减少交易数：{low['total_trades']} vs {high['total_trades']}")
    assert -100 <= low["max_drawdown_pct"] <= 0, "最大回撤须落在 [-100, 0]"
    assert "benchmark_return_pct" in low

    cheap = client.post("/api/v1/backtest/run",
                        json={"spread": 0.0, "commission_pct": 0.0}).json()["data"]["summary"]
    pricey = client.post("/api/v1/backtest/run",
                         json={"spread": 3.0, "commission_pct": 0.05}).json()["data"]["summary"]
    assert cheap["total_return_pct"] > pricey["total_return_pct"], "成本升高应降低收益"


# ===== 17. 准确率样本量（避免小样本误导）=====
def test_accuracy_sample_size():
    client.post("/api/v1/backtest/run", json={"signal_threshold": 0.55})
    a = _data(client.get("/api/v1/stats/accuracy?window=30d"))
    for k in ("sample_7d", "sample_30d", "sample_bullish", "sample_bearish"):
        assert k in a, f"缺少 {k}"
    assert a["sample_30d"] >= 0
    assert a["sample_bullish"] + a["sample_bearish"] == a["sample_30d"] or a["sample_30d"] == 0


# ===== 18. 新闻链接可跳转（前端页面优化 S3）=====
def test_news_url_is_real_link():
    rows = _data(client.get("/api/v1/news?limit=10"))
    assert rows, "新闻不应为空"
    for n in rows:
        assert n.get("url", "").startswith("http"), f"{n['id']} 缺少可用链接"
        assert "example.com" not in n["url"], f"{n['id']} 仍是占位链接"


# ===== 19. 新闻标题含中文概括（title_zh）=====
def test_news_title_zh_summary():
    rows = _data(client.get("/api/v1/news?limit=10"))
    assert rows, "新闻不应为空"
    for n in rows:
        assert "title_zh" in n, f"{n['id']} 缺少 title_zh"
        assert n["title_zh"], f"{n['id']} title_zh 为空"


# ===== 20. 新闻标题不得为“多空方向”式（呼应关键句，而非直接看多/看空）=====
def test_news_title_not_direction_only():
    rows = _data(client.get("/api/v1/news?limit=30"))
    assert rows, "新闻不应为空"
    bad = [
        n["id"] for n in rows
        if "利好黄金" in (n.get("title_zh") or "")
        or "利空黄金" in (n.get("title_zh") or "")
        or "影响中性" in (n.get("title_zh") or "")
    ]
    assert not bad, f"仍存在方向式标题（应避免直接以多空方向作标题）: {bad}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
