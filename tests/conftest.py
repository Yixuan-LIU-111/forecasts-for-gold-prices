"""pytest 全局配置与公共夹具（测试基础设施）。

设计要点
--------
1. **测试库隔离**：在导入任何 ``app.*`` 模块之前改写 ``DATABASE_URL`` 环境变量，
   把测试数据写入 ``.pytest_tmp/gold_test.db``，绝不污染开发库
   ``data/gold_predictor.db``。pydantic-settings 中环境变量优先级高于 ``.env``，
   且 ``app.config.settings`` 是模块级单例，因此**必须在文件最顶部完成设置**。
2. **关闭后台副作用**：测试期间禁用 APScheduler 调度器与新闻实时爬取，
   避免测试进程被真实网络请求 / LLM 调用干扰，保证确定性与执行速度。
3. **会话级诊断**：测试开始前建表 + 播种 demo_data，并打印各表行数。
   表行数为 0 → 种子失败；行数正常但断言失败 → 序列化器/字段对齐问题。
4. **公共夹具**：向所有测试用例提供 ``client``（HTTP 测试客户端）、
   ``db``（数据库会话）、``api``（带响应信封解包的便捷调用器）。
"""
from __future__ import annotations

# ============================================================
# 第 0 步：环境隔离（必须先于任何 app.* 导入执行）
# ============================================================
import os
import shutil
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_TMP_DIR = _PROJECT_ROOT / ".pytest_tmp"
_TMP_DIR.mkdir(parents=True, exist_ok=True)
_TEST_DB = _TMP_DIR / "gold_test.db"

# 允许通过 KEEP_TEST_DB=1 保留上轮测试库（便于排查问题）；默认每轮全新构建
if os.getenv("KEEP_TEST_DB", "0") != "1":
    for suffix in ("", "-shm", "-wal"):
        p = Path(str(_TEST_DB) + suffix)
        if p.exists():
            p.unlink()

os.environ["DATABASE_URL"] = f"sqlite:///{_TEST_DB}"
os.environ["DEMO_MODE"] = "true"          # 走 demo 种子数据，结果可复现
os.environ["SCHEDULER_ENABLED"] = "false"  # 关闭后台调度，避免测试期间写库竞争
os.environ["NEWS_SCRAPE_ENABLED"] = "false"  # 关闭实时爬虫，避免外网依赖
os.environ["DEBUG"] = "false"
os.environ["APP_ENV"] = "test"

# ============================================================
# 第 1 步：常规导入
# ============================================================
import logging  # noqa: E402
import time  # noqa: E402

import pytest  # noqa: E402
from sqlalchemy import select, func  # noqa: E402

logger = logging.getLogger("test.diagnostic")

# 测试报告输出目录
REPORT_DIR = _PROJECT_ROOT / "reports"
REPORT_DIR.mkdir(parents=True, exist_ok=True)


# ============================================================
# 自定义标记注册（与 pytest.ini 保持一致，便于 -m 过滤）
# ============================================================
def pytest_configure(config: pytest.Config) -> None:
    for line in (
        "unit: 单元测试（纯函数/算法，无 IO 依赖）",
        "api: 接口测试（FastAPI TestClient 契约与健壮性）",
        "integration: 集成测试（数据库 + 序列化 + 业务链路）",
        "e2e: 端到端测试（前端页面 + 后端接口联动）",
        "perf: 性能基线测试（响应时间 / 吞吐）",
        "security: 安全基线测试（注入、越权、信息泄露）",
        "slow: 耗时较长的用例（默认可用 -m 'not slow' 跳过）",
        "external: 依赖外部网络或第三方服务的用例（CI 默认跳过）",
    ):
        config.addinivalue_line("markers", line)


# ============================================================
# 会话级：建库 + 播种 + 表行数诊断
# ============================================================
@pytest.fixture(scope="session", autouse=True)
def db_diagnostic():
    """会话级诊断：初始化独立测试库并打印各表行数。"""
    from app.core.seed import init_app
    from app.models.database import (
        SessionLocal, MarketData, FactorData, News, Signal,
        BacktestResult, HawkDoveEvent,
    )
    from app.config import settings

    logger.info("=" * 60)
    logger.info("测试数据库：%s", settings.database_url)
    logger.info("初始化数据库 + 播种 demo_data ...")
    t0 = time.perf_counter()
    try:
        init_app()
        logger.info("init_app() 完成，用时 %.2fs", time.perf_counter() - t0)
    except Exception as e:  # noqa: BLE001
        logger.error("init_app() 失败: %s", e, exc_info=True)
        raise

    db = SessionLocal()
    try:
        tables = {
            "market_data": MarketData,
            "factor_data": FactorData,
            "news": News,
            "signals": Signal,
            "backtest_results": BacktestResult,
            "hawk_dove_events": HawkDoveEvent,
        }
        logger.info("-" * 60)
        logger.info("DB 表行数诊断：")
        all_ok = True
        for name, model in tables.items():
            n = db.execute(select(func.count(model.id))).scalar() or 0
            status = "OK" if n > 0 else "EMPTY(空)"
            if n == 0:
                all_ok = False
            logger.info("  %-20s %6d 行  [%s]", name, n, status)
        logger.info("-" * 60)
        if not all_ok:
            logger.error("存在空表！种子数据未写入，测试将失败。请检查 demo_data/*.json 是否存在")
        else:
            logger.info("所有表均有数据，开始运行测试")
    finally:
        db.close()
    logger.info("=" * 60)

    yield

    # 会话结束：默认清理测试库（KEEP_TEST_DB=1 时保留）
    if os.getenv("KEEP_TEST_DB", "0") != "1":
        try:
            from app.models.database import engine
            engine.dispose()
            for suffix in ("", "-shm", "-wal"):
                p = Path(str(_TEST_DB) + suffix)
                if p.exists():
                    p.unlink()
        except Exception:  # noqa: BLE001
            pass


# ============================================================
# 公共夹具
# ============================================================
@pytest.fixture(scope="session")
def client():
    """FastAPI 测试客户端（会话级复用，避免重复建应用开销）。"""
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as c:
        yield c


@pytest.fixture()
def db():
    """请求级数据库会话，用例结束自动回滚 + 关闭。"""
    from app.models.database import SessionLocal

    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture()
def api(client):
    """便捷调用器：自动校验统一响应信封并返回 data 字段。

    用法::

        def test_x(api):
            data = api.get("/api/v1/factors")
    """

    class _Api:
        @staticmethod
        def raw(method: str, url: str, **kw):
            return client.request(method.upper(), url, **kw)

        @staticmethod
        def get(url: str, expect_code: int = 200, **kw):
            r = client.get(url, **kw)
            assert r.status_code == 200, f"HTTP {r.status_code}: {r.text[:300]}"
            body = r.json()
            assert body["code"] == expect_code, f"业务码 {body['code']} != {expect_code}: {body}"
            return body["data"] if expect_code == 200 else body

        @staticmethod
        def post(url: str, json=None, expect_code: int = 200, **kw):
            r = client.post(url, json=json if json is not None else {}, **kw)
            assert r.status_code == 200, f"HTTP {r.status_code}: {r.text[:300]}"
            body = r.json()
            assert body["code"] == expect_code, f"业务码 {body['code']} != {expect_code}: {body}"
            return body["data"] if expect_code == 200 else body

    return _Api()


@pytest.fixture(scope="session")
def project_root() -> Path:
    """仓库根目录（用于读取前端 HTML、demo_data 等静态资源）。"""
    return _PROJECT_ROOT


@pytest.fixture()
def tmp_sqlite_engine():
    """一次性 SQLite 引擎（用于爬虫落库等需要完全隔离的用例）。"""
    import tempfile
    from sqlalchemy import create_engine

    fd, path = tempfile.mkstemp(suffix=".db", dir=str(_TMP_DIR))
    os.close(fd)
    os.remove(path)
    eng = create_engine(f"sqlite:///{path}")
    try:
        yield eng
    finally:
        eng.dispose()
        for suffix in ("", "-shm", "-wal"):
            p = Path(path + suffix)
            if p.exists():
                p.unlink()


# 兼容：暴露常量供个别用例引用
__all__ = ["REPORT_DIR", "shutil"]
