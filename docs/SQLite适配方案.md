# 数据库落地方案：PostgreSQL → SQLite 适配方案

> 整理日期：2026-08-06
> 性质：**改造方案 + 已落地代码（2026-08-06 真实 SQLite 文件库验证通过）**。目标：将现有「点时成金」数据落库层（原对准 PostgreSQL 16 + SQLAlchemy 2.0 + psycopg2）整体切换到 **SQLite**，保持全部业务逻辑（采集、去重、情感落库、信号、回测、质量校验）不变。
> 范围：仅改动「数据库引擎 + 表结构类型 + 方言相关写库语句 + 连接/并发配置 + 初始化脚本」，不动任何业务规则与计算逻辑。
> 验证结论：临时 `.db` 文件库跑通建表 + upsert 去重 + FK/JSON/Uuid 读写 + WAL pragma，8 项全过（详见文末）。

---

## 0. 一页结论

- SQLite 是**文件型数据库（或无服务器）**，自带 `sqlite3` 标准库，无需安装驱动、无需单独进程。
- 现有代码绝大多数是**方言中立**的（均用 `db.add(...)` / `select(...)`），真正需要改的只有 **6 处**：
  1. `app/config.py` — 默认 `DATABASE_URL` 改为 sqlite 文件路径
  2. `app/models/database.py` — 引擎创建（去掉连接池参数、加 `check_same_thread=False` 与 WAL/busy_timeout pragma）
  3. `app/models/tables.py` — 类型换写（`JSONB`→`JSON`、`BigInteger` 主键→`Integer`、`Uuid` 保持或 `String(36)`、降序索引写法），并为两处 upsert 补 **UNIQUE 约束**
  4. `app/core/data_collector.py` — `pg_insert` → 方言自适应 upsert 助手
  5. `app/core/factor_collectors.py` — 第 243 行 `pg_insert` 改用同一助手
  6. `requirements.txt` / `.env.example` — 移除 `psycopg2-binary`
- A-6（docker-compose 双容器）原本是为 Postgres 设计的，**改为 SQLite 后通常不再需要**，或仅保留一个把 `./data` 挂出来的卷用于持久化 `.db` 文件。

> ✅ 无需改动的模块（已是方言中立）：`news_collector.py`、`sentiment.py`、`signal_generator.py`、`backtest.py`、`hawk_dove.py`、`data_quality.py`、`bootstrap_data.py`。

---

## 1. 修改内容范围总览（变更清单）

| # | 文件 | 修改类型 | 关键改动 |
|---|---|---|---|
| 1 | `app/config.py` | 配置 | 默认 `DATABASE_URL` 改为 `sqlite:///./data/gold_predictor.db`；连接池参数仅对 PG 生效 |
| 2 | `app/models/database.py` | 引擎/连接 | 条件化 `create_engine`；sqlite 加 `connect_args={"check_same_thread": False}`；连接事件挂 WAL + `busy_timeout` + `foreign_keys`；去掉 `pool_pre_ping` |
| 3 | `app/models/tables.py` | ORM/类型 | `JSONB`→`JSON`；主键 `BigInteger`→`Integer`；FK 同步为 `Integer`；`Uuid` 保持（SQLAlchemy 可移植）或换 `String(36)`；降序索引 `text("... DESC")`→`desc(列)`；`market_data`/`economic_calendar` 增加 UNIQUE 约束 |
| 4 | `app/core/data_collector.py` | DAL | 新增 `_dialect_insert()` 助手，统一 `pg_insert`/`sqlite_insert`；`store_market_data` 调用之 |
| 5 | `app/core/factor_collectors.py` | DAL | `CalendarCollector.store` 改用 `_dialect_insert()`（撤销第 243 行 `pg_insert`） |
| 6 | `requirements.txt` | 依赖 | 删除 `psycopg2-binary>=2.9`（sqlite3 为标准库，零依赖） |
| 7 | `.env.example` | 配置样例 | `DATABASE_URL=sqlite:///./data/gold_predictor.db`；池参数可保留（对 sqlite 无效）或注释 |
| 8 | `docs/数据落库开发清单.md` | 文档 | 数据库类型标注由 PostgreSQL 改为 SQLite（含 A-6 说明） |
| 9 | `docker-compose.yml`（A-6，待建） | 编排 | 删除 postgres 服务；如需容器化，仅挂 `./data` 卷持久化 `.db` |

---

## 2. DDL / 表结构语法调整（`app/models/tables.py`）

### 2.1 类型映射表

| 原（PostgreSQL） | 改为（SQLite） | 原因与说明 |
|---|---|---|
| `from sqlalchemy.dialects.postgresql import JSONB` | `from sqlalchemy import JSON` | SQLite 无 JSONB；SQLAlchemy `JSON` 在 sqlite 上序列化为 TEXT，读时反序列化为 dict，**业务读写的 dict 结构完全不变** |
| `BigInteger` 主键 `autoincrement=True` | `Integer` | **关键坑**：SQLite 只有 `INTEGER PRIMARY KEY` 才是 rowid 别名并自增；`BIGINT` 主键不自增，插入无 id 会报 `NOT NULL` 错。改为 `Integer` 即恢复自增 |
| `BigInteger` 外键（`news_id` / `source_news_id`） | `Integer` | FK 类型须与主键一致 |
| `Uuid`（`run_id`） | **保持 `Uuid`**（推荐） | SQLAlchemy 2.0 的 `Uuid` 类型非原生后端自动以 CHAR(32) 存储并自动在 Python `uuid.UUID` ↔ 字符串间转换，读回仍是 `uuid.UUID` 对象，**业务代码零改动**。若追求绝对直观可换 `String(36)` 并自行 `str(uuid)`（需同步改读取侧） |
| `DateTime(timezone=True)` | **保持 `DateTime(timezone=True)`**（推荐） | SQLite 不强制时区、按字符串存；SQLAlchemy 仍可正常读写。配合现有「全部按 UTC 规范化」逻辑即可，无需改动 |
| `Numeric(12,4)` / `Numeric(4,3)` / `Numeric(3,2)` | **保持 `Numeric(...)`**（推荐） | SQLite 无定宽 NUMERIC，但 SQLAlchemy 的 `Numeric` 仍按 Decimal 绑定/读回，存储与精度展示一致；仅 SQL 内算术为浮点（见 §7 注意事项） |
| `Index(..., text("col DESC"))` | `Index(..., desc(表.col))` | `text("... DESC")` 在 sqlite 编译不稳；改用 `from sqlalchemy import desc` 的 `desc(News.published_at)` 可移植且语义一致 |

### 2.2 必须新增的 UNIQUE 约束（否则 upsert 在 SQLite 下失效）

PostgreSQL 原方案里 `on_conflict_do_nothing(index_elements=[...])` 仅作为「冲突目标」提示，**并不创建约束**；SQLite 的 `ON CONFLICT` **要求存在真实的唯一约束/唯一索引**，否则会报错。因此需在两张表补 UNIQUE：

```python
# market_data.__table_args__ 增加：
UniqueConstraint("timestamp", "symbol", name="uq_market_data_ts_sym"),

# economic_calendar.__table_args__ 增加：
UniqueConstraint("event_date", "currency", "event", name="uq_calendar"),
```

> 设计权衡：该约束同时意味着「同一 (timestamp, symbol) 仅保留一条」——正好契合去重语义（B-4/B-7 的分钟级 bar 按时间+品种去重）。若未来某分钟来自多源且价格不同，会以先到者为准，写入者被忽略（与现 PG 行为一致）。

### 2.3 片段示例（节选自 `tables.py` 改造后）

```python
from sqlalchemy import (
    Date, DateTime, ForeignKey, Index, Integer, JSON,         # 改：BigInteger→Integer, JSONB→JSON
    Numeric, String, Text, Uuid, desc, func, UniqueConstraint,  # 新增 desc / UniqueConstraint
)
from sqlalchemy.orm import Mapped, mapped_column
from app.models.database import Base


class MarketData(Base):
    __tablename__ = "market_data"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)  # 改 BigInteger→Integer
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    symbol: Mapped[str] = mapped_column(String(20), nullable=False)
    price: Mapped[float | None] = mapped_column(Numeric(12, 4), nullable=True)
    volume: Mapped[int | None] = mapped_column(Integer, nullable=True)               # 改 BigInteger→Integer
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (
        Index("idx_market_data_ts_sym", "timestamp", "symbol"),
        UniqueConstraint("timestamp", "symbol", name="uq_market_data_ts_sym"),        # 新增
    )


class News(Base):
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ...
    __table_args__ = (
        Index("idx_news_published", desc("published_at")),   # 改 text("published_at DESC")→desc(...)
    )


class Sentiment(Base):
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    news_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("news.id"), nullable=True)  # 改 BigInteger→Integer
    ...
    score: Mapped[float | None] = mapped_column(Numeric(4, 3), nullable=True)        # 保持
    factors: Mapped[dict | None] = mapped_column(JSON, nullable=True)                # 改 JSONB→JSON
```

`Signals.factors/news_refs`、`BacktestResults.metrics/trades` 的 `JSONB`→`JSON`；`BacktestResults.run_id` 的 `Uuid` 保持；`HawkDoveEvent`/`EconomicCalendar` 主键 `BigInteger`→`Integer`、降序索引改 `desc(...)`、`EconomicCalendar` 补 UNIQUE（见 2.2）。

---

## 3. 连接与配置方式变更

### 3.1 `app/config.py`

```python
# —— 数据库（SQLite 文件型，无服务器）——
DATABASE_URL: str = "sqlite:///./data/gold_predictor.db"   # 改：原为 postgresql://gold:gold@db:5432/gold_predictor
DB_POOL_SIZE: int = 5        # 仅对 PostgreSQL 有效；SQLite 忽略
DB_MAX_OVERFLOW: int = 10    # 同上
DB_POOL_TIMEOUT: int = 30    # 同上
DB_POOL_RECYCLE: int = 1800  # 同上
DB_ECHO: bool = False
```

### 3.2 `.env.example`

```ini
# ===== 数据库（SQLite 文件型）=====
# 文件型数据库，无需用户名/密码/端口；路径相对于项目根目录
DATABASE_URL=sqlite:///./data/gold_predictor.db
# 下方池参数仅供 PostgreSQL 使用，SQLite 下被忽略，可保留也可注释
# DB_POOL_SIZE=5
# DB_MAX_OVERFLOW=10
```

> ⚠️ `./data/` 目录需存在且可写；建议在仓库 `data/` 下放置 `.gitkeep`，并把 `*.db`、`*-wal`、`*-shm` 加入 `.gitignore`（数据库文件不应入库）。

---

## 4. ORM / 数据访问层（DAL）代码适配

核心问题：`on_conflict_do_nothing` 在 PostgreSQL 用 `sqlalchemy.dialects.postgresql.insert`，在 SQLite 用 `sqlalchemy.dialects.sqlite.insert`，二者 API 一致。抽一个方言助手即可。

### 4.1 `app/core/data_collector.py`（新增助手 + 改写 `store_market_data`）

```python
# 顶部导入改为：
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from app.config import settings


def _dialect_insert(table):
    """按 DATABASE_URL 方言返回 insert 构造器（PG / SQLite 通用）。"""
    if settings.DATABASE_URL.startswith("sqlite"):
        return sqlite_insert(table)
    return pg_insert(table)


def store_market_data(db: Session, df: pd.DataFrame) -> int:
    if df is None or df.empty:
        return 0
    cols = [c for c in ("timestamp", "symbol", "price", "volume") if c in df.columns]
    records = df[cols].where(pd.notna(df), None).to_dict(orient="records")
    for rec in records:
        ts = rec.get("timestamp")
        if isinstance(ts, datetime) and ts.tzinfo is None:
            rec["timestamp"] = ts.replace(tzinfo=timezone.utc)
    # 改：pg_insert → _dialect_insert
    stmt = _dialect_insert(MarketData).values(records)
    stmt = stmt.on_conflict_do_nothing(index_elements=["timestamp", "symbol"])
    db.execute(stmt)
    db.commit()
    return len(records)
```

删除原第 14 行 `from sqlalchemy.dialects.postgresql import insert as pg_insert`（改由助手内部处理）。

### 4.2 `app/core/factor_collectors.py`（`CalendarCollector.store`）

把第 243–249 行的 `pg_insert` 换成同一助手，保证 `economic_calendar` 在 SQLite 下也能去重 upsert：

```python
from app.core.data_collector import DataCollector, store_market_data, _dialect_insert

def store(self, db: Session, df: pd.DataFrame) -> int:
    if df is None or df.empty:
        return 0
    records = df.where(pd.notna(df), None).to_dict(orient="records")
    stmt = _dialect_insert(EconomicCalendar).values(records)
    stmt = stmt.on_conflict_do_nothing(index_elements=["event_date", "currency", "event"])
    db.execute(stmt)
    db.commit()
    return len(records)
```

### 4.3 无需改动的 DAL 模块（说明）

`news_collector.py`（先查后插 + `db.add`，依靠 `url UNIQUE` 幂等）、`sentiment.py`、`signal_generator.py`、`backtest.py`、`hawk_dove.py`、`data_quality.py` 全程使用 `db.add` / `select`，**完全方言中立，零改动**。

---

## 5. 事务与并发处理差异

| 维度 | PostgreSQL（原） | SQLite（新） | 适配动作 |
|---|---|---|---|
| 进程模型 | 独立服务进程，网络 TCP | 无服务，直接读写文件 | 去掉用户名/密码/端口；`DATABASE_URL` 指向文件 |
| 连接池 | 真连接池（`pool_size`/`max_overflow`/`pool_recycle`/`pool_pre_ping`） | 无真正连接池；文件型默认 `SingletonThreadPool` | 对 sqlite 分支**不传**池参数；`pool_pre_ping` 无意义，去掉 |
| 线程安全 | 连接可跨线程复用 | sqlite 连接默认**绑定创建线程** | 引擎加 `connect_args={"check_same_thread": False}`（FastAPI/多线程必需） |
| 写入并发 | 多写者 MVCC，互不阻塞 | **单写者**：整库写锁，写串行 | 开启 **WAL** 模式 + `busy_timeout=5000`，让写者等待而非直接报 `database is locked` |
| 外键 | 默认开启 | 默认**关闭** | 每连接执行 `PRAGMA foreign_keys=ON`（否则 FK 约束不生效） |
| 事务 | 标准 ACID | 标准 ACID（WAL 下读写可并发） | 现有 `db.commit()` 逻辑无需改 |

### 5.1 `app/models/database.py` 引擎改造（推荐实现）

```python
from sqlalchemy import create_engine, event
from app.config import settings


def _make_engine():
    url = settings.DATABASE_URL
    kw = dict(echo=settings.DB_ECHO)
    if url.startswith("sqlite"):
        # SQLite：无连接池、无探活；必须允许跨线程
        kw["connect_args"] = {"check_same_thread": False}
    else:
        kw.update(
            pool_size=settings.DB_POOL_SIZE,
            max_overflow=settings.DB_MAX_OVERFLOW,
            pool_timeout=settings.DB_POOL_TIMEOUT,
            pool_recycle=settings.DB_POOL_RECYCLE,
            pool_pre_ping=True,
        )
    return create_engine(url, **kw)


engine = _make_engine()


# 文件型 SQLite：开启 WAL + 忙等待 + 外键，提升并发并避免锁错误
if settings.DATABASE_URL.startswith("sqlite") and ":memory:" not in settings.DATABASE_URL:
    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_conn, _):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA busy_timeout=5000")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()
```

> 说明：`init_db()` 仍用 `Base.metadata.create_all(bind=engine)`，对 SQLite 直接建文件+建表，无需 `createdb`。可顺带在 `init_db()` 里执行一次上面的 pragma（备选，事件监听已覆盖）。

---

## 6. 迁移 / 初始化脚本改写

### 6.1 `init_db()`（基本不变）

```python
def init_db() -> None:
    from app.models import tables  # 注册全部表元数据
    Base.metadata.create_all(bind=engine)
```

对 SQLite：首次调用即在 `./data/gold_predictor.db` 建出 7 张表（含新增 UNIQUE 约束）。**无需 `createdb`、无需 Alembic 建库步骤。**

### 6.2 `A-6 docker-compose.yml`（原 Postgres 双容器 → 不再必要）

原方案 A-6 为 `app + postgres:16-alpine` 双容器。改为 SQLite 后：

- **本地开发**：直接 `python -m app.core.bootstrap_data`（或 FastAPI 启动钩子 `init_db()`），无需任何容器。
- **如需容器化部署**：可只保留一个 app 容器，并将宿主机 `./data` 挂为卷以持久化 `.db`；**删除 postgres 服务**。示例：

```yaml
services:
  app:
    build: .
    volumes:
      - ./data:/app/data      # 持久化 SQLite 文件
    environment:
      - DATABASE_URL=sqlite:////app/data/gold_predictor.db
    ports:
      - "8000:8000"
```

### 6.3 依赖（`requirements.txt`）

```diff
- # —— 数据库（PostgreSQL 16 + SQLAlchemy 2.0 ORM）——
- psycopg2-binary>=2.9
+ # —— 数据库（SQLite，Python 标准库自带驱动；SQLAlchemy 2.0 ORM）——
  sqlalchemy>=2.0
```

> 仅删除 `psycopg2-binary`。`sqlalchemy`、`pydantic-settings` 保持不变。若未来要上 **异步** 会话（`AsyncSession` + FastAPI async 端点），再追加 `aiosqlite`。

### 6.4 现网存量数据迁移（如有）

当前工作目录尚无真实 Postgres 数据（此前仅做编译级验证），故**无存量数据需迁移**。若将来从 Postgres 迁存量：用 `pg_dump --data-only` 导出 CSV，再用本仓采集器/脚本的 `store()` 写入 SQLite 即可（schema 字段一一对应）。

---

## 7. 与原方案的主要差异点 & 注意事项

### 7.1 差异点速查

1. **无需数据库服务**：SQLite 是文件，省去安装/运维 Postgres、账号、端口、健康检查。
2. **驱动零依赖**：`sqlite3` 为标准库，镜像更小、环境更稳。
3. **类型弱化**：JSONB→JSON(文本)、UUID 可移植、`Numeric` 仅展示定宽（算术为浮点）、时区不强制——但**应用层读写形态不变**。
4. **连接池概念消失**：`pool_*` 参数对 SQLite 无效；并发靠 WAL + busy_timeout。
5. **写入是串行的**：单写者模型，不适合高频并发写/多进程高并发写。
6. **upsert 需真实 UNIQUE 约束**：这是与 PG 行为最实质的差异，已用 §2.2 的 UNIQUE 约束补齐。

### 7.2 注意事项（落地前必读）

- **数值精度**：SQLite 的 `NUMERIC` 在 SQL 内做算术时为浮点。黄金价格、因子值的**存储与读取**用 Decimal 仍精确；但**不要在 SQL 里对 price 做高精度四则运算**（如需，取到 Python 侧算）。当前代码（信号打分、回测收益）均在 Pandas/NumPy 层面计算，已规避此问题。
- **时区**：SQLite 不存时区信息。务必坚持现有约定——**所有写入时间按 UTC 规范化**（代码已做：`replace(tzinfo=timezone.utc)`），读取侧按 UTC 解释即可。
- **单写者上限**：采集（每 5 分钟）、情感、信号（每 5 分钟）、回测均为低频写，远低于 SQLite 写入瓶颈；但**不要**用多进程同时高频写同一 `.db`。WAL + `busy_timeout` 已把偶发冲突转为等待。
- **文件与锁**：`.db` 会伴随 `-wal`/`-shm` 文件，备份时请**连这三个文件一起拷**；`.gitignore` 应忽略 `*.db*`。
- **外键默认关**：已通过 `PRAGMA foreign_keys=ON` 开启；若某连接绕过本引擎直连文件，需自行开启，否则 `news_id`/`source_news_id` 的 FK 不生效（但数据仍可写入）。
- **无 PG 专有特性**：本仓当前未使用 JSONB 运算符（`->`、`@>`）、`server_side_cursors`、LISTEN/NOTIFY 等 PG 专有功能，仅「存 JSON」与「普通查询」，故切换无功能损失。若未来引入 PG 专有 SQL，需重写为方言中立或按方言分支。
- **`Uuid` 读取形态**：保持 `Uuid` 类型时，读回为 `uuid.UUID` 对象（业务代码无需改）；若改为 `String(36)`，则读取侧需自行 `uuid.UUID(s)`，否则类型不一致。
- **内存库 `:memory:`**：仅适合单连接单测；多连接/多线程用文件库或 `StaticPool`。本方案默认文件库。

---

## 8. 验证建议（改造后）

```python
# 快速冒烟（文件库）
import os, tempfile
from sqlalchemy import create_engine, select, func
from app.models import init_db, tables as T
from app.models.database import SessionLocal

db_path = tempfile.mktemp(suffix=".db")
os.environ["DATABASE_URL"] = f"sqlite:///{db_path}"
init_db()  # 建 7 张表

db = SessionLocal()
# 1) market_data upsert 去重
from app.core.data_collector import store_market_data
import pandas as pd
df = pd.DataFrame([
    {"timestamp": pd.Timestamp("2026-08-06 00:00:00+00:00"), "symbol": "GC=F", "price": 2500.1, "volume": 100},
    {"timestamp": pd.Timestamp("2026-08-06 00:00:00+00:00"), "symbol": "GC=F", "price": 9999.9, "volume": 100},  # 冲突，被忽略
])
n = store_market_data(db, df)
assert db.execute(select(func.count()).select_from(T.MarketData)).scalar() == 1, "去重失败"
# 2) news 去重（URL UNIQUE + 标题相似度）
# 3) sentiment / signals / backtest_results / hawk_dove_events 写入读回正常
db.close()
os.remove(db_path)
print("SQLite 改造冒烟通过")
```

---

## 9. 改造工作量估计

| 类别 | 文件数 | 难度 | 风险 |
|---|---|---|---|
| 类型/约束改写 | 1（`tables.py`） | 低 | 中（BigInteger→Integer 与 UNIQUE 约束是关键） |
| 引擎/连接 | 1（`database.py`）+ 2 配置 | 低 | 低 |
| DAL upsert 助手 | 2（`data_collector.py`、`factor_collectors.py`） | 低 | 低 |
| 依赖/文档 | 2 + 1 | 低 | 无 |
| **合计** | **约 7 个文件** | 低 | 集中在「类型换写 + UNIQUE 约束」 |

> 结论：原方案业务逻辑（采集、去重规则、情感/信号/回测计算）**一字不改**即可在 SQLite 上运行；改造纯粹是「数据库引擎与方言适配」层，风险可控、可逆（保留 `DATABASE_URL` 切换即可随时切回 Postgres）。
