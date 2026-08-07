"""端到端测试：前端页面 × 后端接口联动（无浏览器版）。

策略说明
--------
项目前端是单文件静态页 ``frontend/dashboard.html``，无构建链、无组件测试框架。
引入 Playwright/Selenium 会显著抬高环境成本（浏览器二进制 ~300MB、CI 需额外镜像），
性价比不足。因此端到端采用**两级方案**：

- **L1（本文件，默认执行）**：解析真实 HTML，提取其调用的全部接口路径，
  逐一打到真实后端验证连通与结构；同时做页面静态合规检查。
  优点：零额外依赖、秒级执行、可进 CI 门禁。
- **L2（``scripts/frontend_integration_test.mjs``，按需执行）**：jsdom 加载真实页面 +
  真实后端，执行渲染并捕获运行时错误。需 Node + jsdom，作为发版前人工/定时任务执行。

对应用例编号：E2E-*
"""
from __future__ import annotations

import re

import pytest

pytestmark = pytest.mark.e2e

# 页面必须存在的关键 DOM 锚点（5 个视图的核心容器）
REQUIRED_DOM_IDS = [
    "quoteBox", "signalBox", "factorBox", "newsFeed", "priceChart",   # 仪表盘
    "newsTableBox", "hawkFeed",                                        # 新闻中心
    "btSummaryBox", "eqChart", "runBt",                                # 回测
    "accChart", "dirChart",                                            # 准确率统计
    "dsBox", "modelBox",                                               # 系统设置
]

# 5 个导航视图
REQUIRED_VIEWS = ["dashboard", "news", "backtest", "stats", "settings"]


@pytest.fixture(scope="module")
def html(project_root) -> str:
    """读取真实前端页面源码。"""
    p = project_root / "frontend" / "dashboard.html"
    assert p.exists(), f"前端页面缺失: {p}"
    return p.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def frontend_api_paths(html) -> list[str]:
    """从页面源码中提取其实际调用的所有后端接口路径。"""
    paths = sorted(set(re.findall(r"['\"](/api/v1/[^'\"]*)['\"]", html)))
    assert paths, "未能从页面中解析出任何接口调用"
    return paths


# ============================================================
# E2E-01x 页面资产与结构
# ============================================================
def test_dashboard_served_by_backend(client):
    """E2E-011 正常流程：后端同源托管前端页面，避免跨 origin 取数失败。"""
    r = client.get("/dashboard.html")
    assert r.status_code == 200
    assert "<html" in r.text.lower()
    assert "黄金" in r.text, "页面应包含中文业务标题"


def test_required_dom_anchors_present(html):
    """E2E-012 正常流程：5 个视图的关键 DOM 容器齐备。"""
    missing = [i for i in REQUIRED_DOM_IDS if f'id="{i}"' not in html]
    assert not missing, f"页面缺少关键容器: {missing}"


def test_all_views_declared(html):
    """E2E-013 正常流程：导航声明 5 个视图。"""
    missing = [v for v in REQUIRED_VIEWS if f'data-view="{v}"' not in html]
    assert not missing, f"页面缺少视图: {missing}"


def test_api_base_supports_same_origin(html):
    """E2E-014 边界值：同源部署时 API_BASE 走相对路径，file:// 打开时回退绝对地址。"""
    assert "const API_BASE" in html
    assert "location.protocol === 'file:'" in html, "缺少 file:// 场景兜底"


# ============================================================
# E2E-02x 前后端接口契约联动
# ============================================================
def test_every_frontend_call_hits_a_real_endpoint(client, frontend_api_paths):
    """E2E-021 正常流程：页面调用的每个接口在后端均真实存在且返回统一信封。

    这是防「前端调了不存在的接口」的核心闸门。POST 类接口单独处理。
    """
    failures = []
    for path in frontend_api_paths:
        if path.endswith("/backtest/run"):
            r = client.post(path, json={})
        else:
            r = client.get(path)
        if r.status_code != 200:
            failures.append(f"{path} -> HTTP {r.status_code}")
            continue
        body = r.json()
        if body.get("code") != 200:
            failures.append(f"{path} -> code {body.get('code')}")
    assert not failures, "前端调用的接口异常：\n" + "\n".join(failures)


def test_no_orphan_backend_endpoint_for_core_domains(client, frontend_api_paths):
    """E2E-022 正常流程：核心业务域接口均已被前端接入（无「后端做了前端没用」）。"""
    joined = " ".join(frontend_api_paths)
    for domain in ("/signals/", "/market/", "/factors", "/news",
                   "/backtest/", "/stats/", "/hawk-dove/", "/system/"):
        assert domain in joined, f"核心业务域 {domain} 未被前端接入"


def test_frontend_render_fields_exist_in_response(client):
    """E2E-023 正常流程：页面渲染依赖的关键字段在接口响应中存在（防 undefined 渲染）。"""
    checks = {
        "/api/v1/market/price?range_hours=4h": ["current_price", "change", "change_pct", "prices"],
        "/api/v1/signals/latest": ["direction_en", "probability", "attribution", "bull_bear_score"],
        "/api/v1/factors": ["factors"],
        "/api/v1/system/status": ["db_type", "model_info", "api_usage"],
        "/api/v1/backtest/results": ["summary", "equity_curve", "accuracy"],
    }
    for url, keys in checks.items():
        data = client.get(url).json()["data"]
        for k in keys:
            assert k in data, f"{url} 响应缺少前端依赖字段 {k}"


def test_backtest_button_writes_and_refreshes(client):
    """E2E-024 正常流程：模拟点击「运行回测」→ 写库 → 结果接口读到新值。"""
    run = client.post("/api/v1/backtest/run",
                      json={"initial_capital": 20000, "signal_threshold": 0.58}).json()
    assert run["code"] == 200
    results = client.get("/api/v1/backtest/results").json()["data"]
    assert results["summary"]["initial_capital"] == 20000, "结果接口未反映最新回测参数"


# ============================================================
# E2E-03x 文案合规（对应前端页面优化 S1/S2）
# ============================================================
def test_no_internal_feature_codes_in_page(html):
    """E2E-031 正常流程：页面正文不得出现内部功能点编号 F01/F02…（S1）。"""
    body = re.sub(r"<script[\s\S]*?</script>|<style[\s\S]*?</style>", "", html)
    body = re.sub(r"<!--[\s\S]*?-->", "", body)
    hits = re.findall(r"\bF\d{2}\b", body)
    assert not hits, f"页面残留功能点编号: {sorted(set(hits))}"


@pytest.mark.parametrize("claim", ["PostgreSQL 16", "GPT-4o-mini", "yfinance 实时"])
def test_no_false_tech_claims_hardcoded(html, claim):
    """E2E-032 正常流程：不得硬编码与实际部署不符的技术表述（S2）。"""
    body = re.sub(r"<script[\s\S]*?</script>", "", html)
    assert claim not in body, f"页面硬编码失实表述: {claim}"


def test_news_links_are_external_and_clickable(client):
    """E2E-033 正常流程：新闻标题外链真实可跳转（S3），非占位地址。"""
    rows = client.get("/api/v1/news?limit=20").json()["data"]
    assert rows
    for n in rows:
        assert n["url"].startswith("http"), f"{n['id']} 链接非法: {n['url']}"
        assert "example.com" not in n["url"], f"{n['id']} 仍为占位链接"


def test_data_sources_driven_by_backend(client, html):
    """E2E-034 正常流程：数据源清单由后端 data-sources 驱动，非前端写死（S5）。"""
    assert "/api/v1/system/data-sources" in html, "页面未接入数据源接口"
    rows = client.get("/api/v1/system/data-sources").json()["data"]
    assert rows, "数据源不应为空"
    codes = {r["indicator_code"] for r in rows}
    assert {"XAUUSD", "DXY", "VIX", "TIPS"} <= codes, f"核心指标缺失: {codes}"


def test_model_info_driven_by_backend(client, html):
    """E2E-035 正常流程：模型配置由后端 model_info 驱动（S6）。"""
    assert "modelBox" in html
    mi = client.get("/api/v1/system/status").json()["data"]["model_info"]
    for k in ("name", "status", "is_real_model", "demo_mode",
              "signal_threshold", "available_indicators"):
        assert k in mi, f"model_info 缺少 {k}"


# ============================================================
# E2E-04x 浏览器级回归（可选，需 Node + jsdom）
# ============================================================
@pytest.mark.slow
@pytest.mark.external
def test_jsdom_regression_script_available(project_root):
    """E2E-041 环境检查：L2 浏览器级回归脚本存在且可被定位。

    实际执行需先启动后端，再运行::

        node scripts/frontend_integration_test.mjs
    """
    script = project_root / "scripts" / "frontend_integration_test.mjs"
    assert script.exists(), "缺少 jsdom 回归脚本"
    src = script.read_text(encoding="utf-8")
    assert "JSDOM" in src and "dashboard.html" in src
