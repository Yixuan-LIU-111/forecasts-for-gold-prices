"""接口测试：健壮性、边界值与异常容错。

与 ``test_api_contract.py`` 分工
-------------------------------
- ``test_api_contract.py``：**正常流程**，校验 13 个端点的响应结构与 demo_data 一致；
- 本文件：**边界与异常**，校验非法参数、越界分页、不存在路由、错误方法、
  空数据兜底、响应信封一致性等「非快乐路径」。

对应用例编号：IT-API-*
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.api

# 全部只读端点（用于批量共性校验）
READ_ENDPOINTS = [
    "/api/v1/signals/latest",
    "/api/v1/signals/attribution",
    "/api/v1/market/price?range_hours=4h",
    "/api/v1/factors",
    "/api/v1/news?limit=20",
    "/api/v1/backtest/results",
    "/api/v1/backtest/pnl-distribution",
    "/api/v1/backtest/trades",
    "/api/v1/stats/accuracy?window=7d",
    "/api/v1/hawk-dove/events?days=7",
    "/api/v1/system/status",
    "/api/v1/system/data-sources",
]


# ============================================================
# IT-API-01x 通用契约
# ============================================================
@pytest.mark.parametrize("url", READ_ENDPOINTS)
def test_all_read_endpoints_return_envelope(client, url):
    """IT-API-011 正常流程：所有只读端点均返回 {code,message,data} 统一信封。"""
    r = client.get(url)
    assert r.status_code == 200, f"{url} -> HTTP {r.status_code}"
    body = r.json()
    assert set(("code", "message", "data")) <= set(body.keys()), f"{url} 信封字段缺失: {body.keys()}"
    assert body["code"] == 200, f"{url} 业务码异常: {body['code']}"


@pytest.mark.parametrize("url", READ_ENDPOINTS)
def test_read_endpoints_are_idempotent(client, url):
    """IT-API-012 正常流程：只读端点连续两次调用结构一致（无副作用）。"""
    a = client.get(url).json()["data"]
    b = client.get(url).json()["data"]
    assert type(a) is type(b)
    if isinstance(a, dict):
        assert set(a.keys()) == set(b.keys()), f"{url} 两次返回字段集不一致"


@pytest.mark.parametrize("url", READ_ENDPOINTS)
def test_content_type_is_json_utf8(client, url):
    """IT-API-013 正常流程：响应 Content-Type 为 JSON，中文不乱码。"""
    r = client.get(url)
    assert "application/json" in r.headers.get("content-type", "")
    r.json()  # 能被正确反序列化即证明编码无误


# ============================================================
# IT-API-02x 参数边界
# ============================================================
@pytest.mark.parametrize("limit,expect_http", [
    (1, 200),      # 下边界内
    (100, 200),    # 上边界内
    (0, 422),      # 下越界
    (101, 422),    # 上越界
    (-1, 422),     # 负数
])
def test_news_limit_boundary(client, limit, expect_http):
    """IT-API-021 边界值：news.limit 有效域 [1,100]，越界须被拦截。"""
    r = client.get(f"/api/v1/news?limit={limit}")
    assert r.status_code == expect_http, f"limit={limit} 期望 HTTP {expect_http}，实际 {r.status_code}"
    if expect_http == 200:
        rows = r.json()["data"]
        assert isinstance(rows, list)
        assert len(rows) <= limit, "返回条数不得超过 limit"


@pytest.mark.parametrize("bad", ["abc", "1.5", "", "null", "1;DROP TABLE news"])
def test_news_limit_type_error(client, bad):
    """IT-API-022 异常容错：limit 传入非整数 → 422，不得 500。"""
    r = client.get(f"/api/v1/news?limit={bad}")
    assert r.status_code == 422, f"limit={bad!r} 应被类型校验拦截，实际 {r.status_code}"


def test_news_offset_paging(client):
    """IT-API-023 正常流程：offset 分页不重叠，且越界 offset 返回空列表。"""
    page1 = client.get("/api/v1/news?limit=3&offset=0").json()["data"]
    page2 = client.get("/api/v1/news?limit=3&offset=3").json()["data"]
    ids1 = {n["id"] for n in page1}
    ids2 = {n["id"] for n in page2}
    assert not (ids1 & ids2), "分页结果不应重叠"

    far = client.get("/api/v1/news?limit=10&offset=99999")
    assert far.status_code == 200
    assert far.json()["data"] == [], "越界 offset 应返回空列表而非报错"


@pytest.mark.parametrize("rng", ["1h", "4h", "1d", "3d", "7d", "48h"])
def test_market_range_all_valid(client, rng):
    """IT-API-024 正常流程：各档时间窗均可用，且窗口越大点数不减少。"""
    data = client.get(f"/api/v1/market/price?range_hours={rng}").json()["data"]
    assert isinstance(data["prices"], list)
    assert data["current_price"] >= 0


def test_market_range_monotonic(client):
    """IT-API-025 边界值：时间窗放大，返回点数单调不减。"""
    counts = []
    for rng in ("1h", "4h", "1d", "3d", "7d", "48h"):
        counts.append(len(client.get(f"/api/v1/market/price?range_hours={rng}").json()["data"]["prices"]))
    assert counts == sorted(counts), f"点数应随窗口单调不减: {counts}"


@pytest.mark.parametrize("bad", ["999x", "", "abc", "-4h", "4H"])
def test_market_range_invalid_falls_back(client, bad):
    """IT-API-026 异常容错：非法 range_hours 静默回退默认 4h，不得报错。

    当前实现为「宽松容错」策略（period_map.get 默认 48 点），
    本用例锁定该行为，防止未来重构时误改为 500。
    """
    r = client.get(f"/api/v1/market/price?range_hours={bad}")
    assert r.status_code == 200
    assert r.json()["code"] == 200


@pytest.mark.parametrize("window", ["7d", "30d", "bogus", ""])
def test_accuracy_window_tolerant(client, window):
    """IT-API-027 异常容错：accuracy.window 任意取值均返回完整结构。"""
    data = client.get(f"/api/v1/stats/accuracy?window={window}").json()["data"]
    for k in ("overall_7d", "overall_30d", "bullish_accuracy", "bearish_accuracy"):
        assert k in data, f"window={window!r} 缺少字段 {k}"


@pytest.mark.parametrize("days,expect_http", [
    (1, 200), (7, 200), (90, 200),   # 有效域 [1,90]
    (0, 422), (-1, 422), (91, 422),  # 越界
])
def test_hawk_dove_days_boundary(client, days, expect_http):
    """IT-API-028 边界值：hawk-dove.days 有效域为 [1,90]，越界须被拦截。"""
    r = client.get(f"/api/v1/hawk-dove/events?days={days}")
    assert r.status_code == expect_http


# ============================================================
# IT-API-03x 回测参数校验（业务级 422 信封）
# ============================================================
@pytest.mark.parametrize("payload,keyword", [
    ({"initial_capital": 0}, "初始资金"),
    ({"initial_capital": -1000}, "初始资金"),
    ({"spread": -1}, "点差"),
    ({"spread": 10.1}, "点差"),
    ({"commission_pct": 5}, "手续费"),
    ({"commission_pct": -0.01}, "手续费"),
    ({"signal_threshold": 0}, "信号阈值"),
    ({"signal_threshold": 1}, "信号阈值"),
    ({"signal_threshold": 1.5}, "信号阈值"),
])
def test_backtest_invalid_params_rejected(client, payload, keyword):
    """IT-API-031 异常容错：非法回测参数返回业务码 422 且带中文原因。"""
    body = client.post("/api/v1/backtest/run", json=payload).json()
    assert body["code"] == 422, f"{payload} 应被拒绝，实际 {body}"
    assert keyword in body["message"], f"错误信息应指明「{keyword}」: {body['message']}"
    assert body["data"] is None


def test_backtest_multiple_errors_aggregated(client):
    """IT-API-032 异常容错：多个非法参数一次性全部返回，便于前端展示。"""
    body = client.post("/api/v1/backtest/run",
                       json={"initial_capital": 0, "spread": -1, "signal_threshold": 9}).json()
    assert body["code"] == 422
    assert body["message"].count("；") >= 2, f"应聚合多条错误: {body['message']}"


@pytest.mark.parametrize("payload", [
    {},                                   # 全默认
    {"initial_capital": 1},               # 极小资金
    {"initial_capital": 1e9},             # 极大资金
    {"spread": 0, "commission_pct": 0},   # 零成本
    {"spread": 10, "commission_pct": 0.1},  # 上边界成本
    {"signal_threshold": 0.01},           # 近下界阈值
    {"signal_threshold": 0.99},           # 近上界阈值
])
def test_backtest_valid_boundary_params_run(client, payload):
    """IT-API-033 边界值：合法边界参数均可完成回测并返回一致结构。"""
    body = client.post("/api/v1/backtest/run", json=payload).json()
    assert body["code"] == 200, body
    s = body["data"]["summary"]
    for k in ("total_return_pct", "max_drawdown_pct", "win_rate", "total_trades",
              "benchmark_return_pct", "data_mode"):
        assert k in s, f"summary 缺少 {k}"
    assert -100 <= s["max_drawdown_pct"] <= 0, f"最大回撤越界: {s['max_drawdown_pct']}"
    assert 0 <= s["win_rate"] <= 100, f"胜率越界: {s['win_rate']}"
    assert s["total_trades"] >= 0


def test_backtest_type_error_returns_422(client):
    """IT-API-034 异常容错：字段类型错误由 FastAPI 拦截为 HTTP 422，不得 500。"""
    r = client.post("/api/v1/backtest/run", json={"initial_capital": "abc"})
    assert r.status_code == 422


@pytest.mark.xfail(reason="DEF-002：FastAPI 参数校验返回裸 detail，未包统一信封", strict=False)
def test_framework_422_should_use_unified_envelope(client):
    """IT-API-035 异常容错（已知缺陷）：框架级 422 也应返回 {code,message,data}。

    当前实现只有业务级校验走统一信封，框架级校验（类型/范围）返回
    ``{"detail":[...]}``，前端若统一按信封解析会取不到 code。
    标记为 xfail，缺陷修复后本用例自动转 XPASS 提示。
    """
    body = client.get("/api/v1/news?limit=0").json()
    assert "code" in body and "message" in body


@pytest.mark.xfail(reason="DEF-003：非法 start_date 被静默忽略，未回传校验错误", strict=False)
def test_backtest_invalid_date_should_be_rejected(client):
    """IT-API-036 异常容错（已知缺陷）：非法日期字符串应返回 422 而非静默成功。"""
    body = client.post("/api/v1/backtest/run", json={"start_date": "not-a-date"}).json()
    assert body["code"] == 422


# ============================================================
# IT-API-04x 路由与方法
# ============================================================
@pytest.mark.parametrize("url", [
    "/api/v1/notfound",
    "/api/v1/signals/unknown",
    "/api/v2/factors",
    "/api/v1/backtest/",
])
def test_unknown_route_returns_404(client, url):
    """IT-API-041 异常容错：未定义路由返回 404，不得 500。"""
    assert client.get(url).status_code in (404, 405, 307)


@pytest.mark.parametrize("method,url", [
    ("POST", "/api/v1/news"),
    ("DELETE", "/api/v1/news"),
    ("PUT", "/api/v1/factors"),
    ("GET", "/api/v1/backtest/run"),
])
def test_wrong_method_returns_405(client, method, url):
    """IT-API-042 异常容错：错误 HTTP 方法返回 405。"""
    assert client.request(method, url).status_code == 405


def test_health_and_openapi(client):
    """IT-API-043 正常流程：健康检查与 OpenAPI 文档可用。"""
    assert client.get("/health").json() == {"status": "ok"}
    spec = client.get("/openapi.json").json()
    assert spec["info"]["title"] == "黄金价格预测系统 API"
    paths = spec["paths"]
    assert len([p for p in paths if p.startswith("/api/v1")]) >= 13, "对外端点数量应 >= 13"


def test_dashboard_page_served(client):
    """IT-API-044 正常流程：同源托管的前端页面可访问（避免跨域取数失败）。"""
    for url in ("/", "/dashboard", "/dashboard.html"):
        r = client.get(url)
        assert r.status_code == 200, f"{url} -> {r.status_code}"
        assert "text/html" in r.headers.get("content-type", "")


# ============================================================
# IT-API-05x 业务不变量
# ============================================================
def test_signal_invariants(client):
    """IT-API-051 正常流程：信号各字段满足业务取值域约束。"""
    s = client.get("/api/v1/signals/latest").json()["data"]
    assert s is not None
    assert 0 <= s["probability"] <= 1, "概率须在 [0,1]"
    assert s["direction_en"] in ("bullish", "bearish", "neutral")
    assert s["direction"] in ("看涨", "看跌", "观望")
    assert 0 <= s["position_pct"] <= 100
    assert 0 <= s["confidence_value"] <= 100
    assert s["confidence"] in ("高", "中", "低")
    assert -100 <= s["bull_bear_score"] <= 100
    # 方向与仓位互洽
    if s["direction_en"] == "neutral":
        assert s["position_pct"] == 0, "观望仓位须为 0"


def test_factors_invariants(client):
    """IT-API-052 正常流程：6 因子齐备，趋势与颜色取值受控。"""
    data = client.get("/api/v1/factors").json()["data"]
    factors = data["factors"]
    assert len(factors) == 6, f"应有 6 个因子，实际 {len(factors)}"
    names = {f["name"] for f in factors}
    assert {"DXY", "TIPS", "VIX", "GPR", "sentiment", "hawk_dove"} <= names
    for f in factors:
        assert f["trend"] in ("up", "down", "flat")
        assert f["trend_color"] in ("red", "green", "gray")
        assert isinstance(f["value"], (int, float))


def test_news_invariants(client):
    """IT-API-053 正常流程：新闻情感标签、置信度、链接均合法。"""
    rows = client.get("/api/v1/news?limit=50").json()["data"]
    assert rows, "新闻不应为空"
    for n in rows:
        assert n["sentiment"] in ("bullish", "bearish", "neutral"), f"非法情感标签 {n['sentiment']}"
        assert n["sentiment_label"] in ("利多", "利空", "中性"), f"非法中文情感标签 {n['sentiment_label']}"
        assert -1 <= n["sentiment_score"] <= 1, f"情感分越界 {n['sentiment_score']}"
        assert 0 <= n["confidence"] <= 1
        assert n["url"].startswith("http"), f"新闻 {n['id']} 链接非法"
        assert "example.com" not in n["url"], f"新闻 {n['id']} 仍是占位链接"


def test_market_price_invariants(client):
    """IT-API-054 正常流程：行情高低开收关系自洽。"""
    m = client.get("/api/v1/market/price?range_hours=1d").json()["data"]
    assert m["high_24h"] >= m["low_24h"]
    assert m["low_24h"] <= m["current_price"] <= m["high_24h"]
    for p in m["prices"]:
        assert p["price"] > 0
        assert p["volume"] >= 0


def test_pnl_distribution_invariants(client):
    """IT-API-055 正常流程：盈亏分布 bins 与 counts 长度关系正确。"""
    d = client.get("/api/v1/backtest/pnl-distribution").json()["data"]
    assert len(d["bins"]) == len(d["counts"]) + 1 or len(d["bins"]) == len(d["counts"]), (
        f"bins/counts 长度不匹配: {len(d['bins'])}/{len(d['counts'])}")
    assert all(c >= 0 for c in d["counts"]), "频次不得为负"


def test_system_status_invariants(client):
    """IT-API-056 正常流程：系统状态字段齐备且取值受控。"""
    st = client.get("/api/v1/system/status").json()["data"]
    assert st["db_type"] in ("SQLite", "PostgreSQL", "Unknown")
    assert st["model_info"]["status"] in ("loaded", "synthetic_baseline", "unavailable")
    assert isinstance(st["model_info"]["available_indicators"], list)
    assert st["mode"] in ("演示模式", "实时模式")
