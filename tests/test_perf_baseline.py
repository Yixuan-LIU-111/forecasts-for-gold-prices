"""性能基线测试：接口响应时间与并发稳定性。

定位说明
--------
这是**基线守门**而非压测。目标是在 CI 中低成本地拦截「某次改动让接口慢一个数量级」
这类回归，不追求精确的容量数字。真实压测（locust / wrk）属于上线前专项，
不纳入日常回归（见测试方案 §3.5）。

阈值设定依据：本机 SQLite + demo 数据量（market_data 49 行 / news 10 条），
只读接口 P95 应远小于 200ms；回测为计算密集型，单次放宽到 2s。
CI 机器性能波动较大，阈值已留 5~10 倍余量，避免假失败。

对应用例编号：PERF-*
"""
from __future__ import annotations

import statistics
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

pytestmark = [pytest.mark.perf, pytest.mark.slow]

# 只读接口 → P95 阈值（毫秒）
READ_SLA_MS = {
    "/api/v1/signals/latest": 200,
    "/api/v1/signals/attribution": 200,
    "/api/v1/market/price?range_hours=7d": 300,
    "/api/v1/factors": 300,
    "/api/v1/news?limit=50": 300,
    "/api/v1/backtest/results": 500,
    "/api/v1/stats/accuracy?window=30d": 200,
    "/api/v1/hawk-dove/events?days=30": 200,
    "/api/v1/system/status": 500,
    "/api/v1/system/data-sources": 200,
}

WARMUP = 3
ROUNDS = 20


def _percentile(values: list[float], pct: float) -> float:
    """计算百分位（线性插值，样本量小也稳定）。"""
    if not values:
        return 0.0
    s = sorted(values)
    k = (len(s) - 1) * pct
    lo, hi = int(k), min(int(k) + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


@pytest.mark.parametrize("url,sla_ms", list(READ_SLA_MS.items()))
def test_read_endpoint_latency(client, url, sla_ms, record_property):
    """PERF-001 正常流程：只读接口 P95 响应时间不超过基线阈值。"""
    for _ in range(WARMUP):
        client.get(url)

    costs = []
    for _ in range(ROUNDS):
        t0 = time.perf_counter()
        r = client.get(url)
        costs.append((time.perf_counter() - t0) * 1000)
        assert r.status_code == 200

    p50 = _percentile(costs, 0.50)
    p95 = _percentile(costs, 0.95)
    # 写入 junit 报告属性，便于在验收报告中汇总性能数据
    record_property("p50_ms", round(p50, 2))
    record_property("p95_ms", round(p95, 2))
    record_property("max_ms", round(max(costs), 2))
    assert p95 <= sla_ms, (
        f"{url} P95={p95:.1f}ms 超过基线 {sla_ms}ms（P50={p50:.1f}ms, max={max(costs):.1f}ms）")


def test_backtest_run_latency(client, record_property):
    """PERF-002 边界值：回测为计算密集型，单次执行不超过 2s。"""
    costs = []
    for _ in range(5):
        t0 = time.perf_counter()
        r = client.post("/api/v1/backtest/run", json={"signal_threshold": 0.55})
        costs.append((time.perf_counter() - t0) * 1000)
        assert r.json()["code"] == 200
    avg = statistics.mean(costs)
    record_property("avg_ms", round(avg, 2))
    record_property("max_ms", round(max(costs), 2))
    assert max(costs) <= 2000, f"回测最慢一次 {max(costs):.0f}ms 超过 2000ms"


def test_concurrent_read_stability(client, record_property):
    """PERF-003 边界值：20 并发只读请求全部成功，无 5xx、无数据库锁错误。

    SQLite WAL 模式下并发读安全，本用例锁定该前提；若未来切 PostgreSQL，
    阈值可直接上调。
    """
    urls = list(READ_SLA_MS.keys())

    def _hit(i: int):
        u = urls[i % len(urls)]
        t0 = time.perf_counter()
        r = client.get(u)
        return u, r.status_code, (time.perf_counter() - t0) * 1000

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(_hit, range(40)))

    bad = [(u, c) for u, c, _ in results if c != 200]
    costs = [c for _, _, c in results]
    record_property("concurrent_p95_ms", round(_percentile(costs, 0.95), 2))
    assert not bad, f"并发下出现失败请求: {bad[:5]}"
    assert _percentile(costs, 0.95) <= 1500, f"并发 P95 {_percentile(costs, 0.95):.0f}ms 过高"


def test_large_payload_endpoint(client, record_property):
    """PERF-004 边界值：最大数据量接口（7d 行情 + 100 条新闻）响应体大小与耗时可控。"""
    t0 = time.perf_counter()
    r1 = client.get("/api/v1/market/price?range_hours=7d")
    r2 = client.get("/api/v1/news?limit=100")
    cost = (time.perf_counter() - t0) * 1000
    size_kb = (len(r1.content) + len(r2.content)) / 1024
    record_property("payload_kb", round(size_kb, 1))
    record_property("cost_ms", round(cost, 2))
    assert cost <= 1000, f"最大负载耗时 {cost:.0f}ms"
    assert size_kb <= 2048, f"响应体 {size_kb:.0f}KB 过大，需分页或裁剪字段"


def test_no_n_plus_one_on_factors(client, record_property):
    """PERF-005 边界值：因子接口耗时不应随因子数量线性劣化（当前逐因子查询，留观测点）。

    ``serialize_factors`` 对 6 个因子各执行一次 SELECT（6 次查询）。
    数据量小暂不构成瓶颈，本用例记录耗时作为将来优化为单次聚合查询的基线。
    """
    costs = []
    for _ in range(10):
        t0 = time.perf_counter()
        client.get("/api/v1/factors")
        costs.append((time.perf_counter() - t0) * 1000)
    p95 = _percentile(costs, 0.95)
    record_property("factors_p95_ms", round(p95, 2))
    assert p95 <= 300, f"因子接口 P95 {p95:.0f}ms，疑似 N+1 查询劣化"
