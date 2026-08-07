# `forecasts-for-gold-prices-main` 删除安全性评估

> 评估日期：2026-08-06 ｜ 评估性质：**只读调查，未执行任何删除或移动**
> 评估对象：`/Users/echo/Desktop/forecasts for gold prices/forecasts-for-gold-prices-main/`（5.0 MB）

---

## 0. 命名澄清

用户描述的「`forecasts-for-gold-prices-main` 副本」文件夹，在磁盘上**并不存在**该字面名称。全盘检索确认：

| 路径 | 说明 |
|---|---|
| `~/Desktop/forecasts for gold prices/forecasts-for-gold-prices-main/` | 唯一匹配对象，即本次评估目标 |
| `~/Desktop/点时成金/forecasts for gold prices_bak0806/` | 完整备份（含 main 目录） |
| `~/Desktop/点时成金/forecasts for gold prices_bak0805/`、`_bak0803/` | 早期备份（**不含** main 目录） |

「副本」是此前架构文档中对它的称呼（团队 GitHub 主干的本地拷贝），非文件夹实名。

---

## 1. 结论（先行）

**当前状态下不建议直接删除。** 该目录仍持有 **5 项主项目尚不具备的资产**。

但删除的**技术障碍已全部清除**：无代码引用、无进程占用、后端功能 100% 被替代、存在零差异外部备份。因此推荐路径是：

> **先迁移 5 项独有资产 → 验证通过 → 再删除目录**

---

## 2. 内容盘点

```
forecasts-for-gold-prices-main/          5.0 MB
├── docs/            3.3 MB   13 份文档（12 份与主项目逐字节相同）
├── app/             708 KB   FastAPI 后端 + Streamlit 仪表盘
├── models/          384 KB   predictor.joblib
├── data/            212 KB   gold_predictor.db
├── 7 个爬虫目录      236 KB   dfii10/dxy/epu/fred/gpr/investing_calendar/vix
├── tests/            44 KB   conftest.py + test_api_contract.py
├── 项目方案.md        88 KB   ★ 唯一副本
├── Dockerfile / docker-compose.yml / pytest.ini   ★ 主项目无
├── .env / .env.example / .gitignore / .streamlit/
└── requirements.txt / read_excel.py
```

文件类型：91 个 `.py`、13 个 `.md`、5 个 `.json`、2 个 `.xlsx`、1 个 `.docx`、1 个 `.joblib`、1 个 `.db`。

---

## 3. 判断依据

### 3.1 引用检查 —— 无任何程序引用 ✅

全项目按 `*.py / *.md / *.json / *.yml / *.toml / *.ini / *.sh / *.html` 检索 `forecasts-for-gold-prices-main`：

- **零处 `import`、零处路径拼接、零处配置指向**
- 全部 16 处命中均为**文档正文或代码注释中的文字提及**（`app/config.py` 头注释、`docs/项目架构梳理.md`、记忆日志等）

删除后不会造成任何 `ImportError` 或 `FileNotFoundError`。

### 3.2 进程占用 —— 无 ✅

`lsof +D` 与 `ps aux` 均无输出，无任何进程持有该目录内文件句柄。

### 3.3 版本控制 —— 未被 Git 追踪 ⚠️

`.git` 位于主项目根，**目录内无独立仓库**；`git ls-files` 对该路径返回 **0 个文件**（完全 untracked）。

> **含义：删除后 Git 无法恢复，唯一恢复来源是 bak0806 备份。**

### 3.4 后端功能 —— 已被完整替代 ✅（实测验证）

取该目录自带的 API 契约测试（`tests/test_api_contract.py`，12 个用例），**拷至 `/tmp` 隔离 `sys.path` 后**指向主项目运行：

```
app.main -> /Users/echo/Desktop/forecasts for gold prices/app/main.py
............                                          [100%]
12 passed in 0.98s
```

> 注：直接在原目录跑 pytest 会因 `rootdir` 探测把 main 目录插入 `sys.path[0]`，实际测的是它自己 —— 该结果无效，必须隔离后重测。

覆盖端点：`/api/v1/signals/latest`、`signals/attribution`、`market/price`、`factors`、`news`、`backtest/results`、`backtest/run`、`stats/accuracy`、`system/status`。**主项目已完全承接其后端契约。**

### 3.5 逐目录替代关系核对

| 内容 | 结论 | 依据 |
|---|---|---|
| `app/**.py` | **已全部合并** | main 独有 py 文件差集为空 |
| `app/dashboard/` | **主项目版本更优** | 主项目多 `assets/`；main 版为涨绿跌红基线（违反用户硬约束），主项目已修正为涨红跌绿 |
| `docs/` 13 份 | **12 份逐字节相同** | 仅 `项目方案V1.0.md` 差 2 行表格（宏观数据、长期因子两行） |
| 7 个爬虫 | **6 个完全一致** | 仅 `gpr_scraper/scraper.py` 差一行导入写法（main 用 `from gpr_scraper.config`，主项目用裸名 `from config` —— 后者是为适配 `factor_collectors` 的 `sys.path` 隔离加载，**不可回改**） |
| `.streamlit/`、`read_excel.py`、`.gitignore` | **完全一致** | — |
| `data/gold_predictor.db` | **无独有数据** | 两库均只有 `backtest_results` 表 4 行；内容 MD5 不同（不同回测批次），可通过 `POST /api/v1/backtest/run` 重新生成 |

---

## 4. 尚未迁移的独有资产（删除即丢失）

| # | 资产 | 主项目状态 | 价值 | 建议 |
|---|---|---|---|---|
| 1 | **`项目方案.md`**（2028 行 / 142 标题） | **无** | **高** | **必迁** |
| 2 | **`Dockerfile` + `docker-compose.yml`** | **无** | 中高 | 建议迁 |
| 3 | **`pytest.ini` + `tests/{conftest,test_api_contract}.py`** | **无** | **高** | **必迁** |
| 4 | `requirements.txt` 中 `streamlit-autorefresh>=1.0` | **缺** | 中 | 补一行 |
| 5 | `.env` / `.env.example` 的 9 个后端键 | **缺** | 中 | 补进 `.env.example` |
| 6 | `models/predictor.joblib`（392,282 B） | 有**不同**版本（393,417 B） | 低-中 | 存疑，见下 |

### 4.1 关于 `项目方案.md`（最高优先级）

三份方案文档的关系：

| 文档 | 行数 | 标题数 | 位置 |
|---|---|---|---|
| `main/项目方案.md` | **2028** | **142** | **仅 main 有** |
| `docs/项目方案V1.0.md` | 1416 | 123 | 两边都有 |
| `docs/项目方案V2.0.md` | 473 | 39 | 仅主项目有（精简修订版） |

`main/项目方案.md` 比 V1.0 多 612 行，独有章节包括：

- **§11 API 接口规格全套** —— 11.1 设计原则 / 11.2 内部接口 / 11.3 RESTful 端点总览（对齐 client.py 12 函数）/ 11.4 统一响应格式 / 11.5 详细接口规格 / 11.6 错误码 / 11.7 前后端契约一致性校验
- **§19 后端功能实施详细设计** —— 19.1 整体架构 / 19.2 爬虫适配与集成 / 19.3 采集调度策略 / 19.4 DEMO-LIVE 模式切换 / 19.5 实现优先级 / 19.6 验收标准
- **完整特征工程清单** —— 价格序列 / 市场 / 情感 / 政策 / 地缘 / 交互 / 目标变量 / 扩展特征分组定义

V2.0 仅 473 行，**不覆盖**这些细节。这是全项目唯一一份记录 API 契约与后端设计决策的文档。

### 4.2 关于 `.env`（无安全风险）

已脱敏检查：`OPENAI_API_KEY`、`NEWSAPI_KEY` **均为空值**，非真实凭据，删除无泄密/丢密风险。但其中 9 个配置键（`DEMO_MODE`、`DEBUG`、`API_HOST`、`API_PORT`、`SIGNAL_INTERVAL_SECONDS`、`COLLECT_INTERVAL_SECONDS`、`NEWSAPI_KEY`、`NEWSAPI_DAILY_LIMIT`、`LLM_DAILY_BUDGET_USD`）主项目 `.env.example` 中没有 —— 而合并后的 `app/config.py` 是支持这些字段的，说明主项目的示例配置文件已落后于代码。

主项目 `.env.example` 独有的 6 个键（`APP_ENV`、`LOG_LEVEL`、`LLM_MAX_CONCURRENCY`、`OPENAI_BASE_URL`、`OPENAI_TEMPERATURE`、`OPENAI_TIMEOUT`）main 也没有 —— 两边**互补**，应合并成完整清单。

### 4.3 关于 `predictor.joblib`（存疑项）

两个文件**二进制不同**：main 版 392,282 B（8/5 22:12），主项目版 393,417 B（8/6 13:08）。主项目的更新且已被 `app/core/predictor.py` 正常加载（契约测试中 `system_status` 用例通过）。main 版是团队原始训练权重，若需保留可复现性可另行归档；否则依赖 bak0806 备份即可。

---

## 5. 安全垫状况

| 检查项 | 结果 |
|---|---|
| `bak0806` 是否含该目录 | ✅ 含，5.0 MB |
| 与当前目录差异 | ✅ **0 个差异条目**（排除 `__pycache__`/`.DS_Store`/`.pytest_cache`） |
| 6 项独有资产是否齐全 | ✅ 全部存在（项目方案.md、Dockerfile、compose、pytest.ini、.env、.env.example、两个测试文件、joblib、db） |
| `bak0805` / `bak0803` | ❌ **不含** main 目录 |

**bak0806 是唯一且完整的恢复来源。** 删除前请勿清理该备份。

---

## 6. 最终建议

### 推荐方案：先迁移，后删除

按优先级执行以下迁移（均为复制，不影响现有文件）：

1. `项目方案.md` → `docs/项目方案V1.0-完整版.md`（避免与现有 V1.0 重名）
2. `tests/conftest.py`、`tests/test_api_contract.py` → 主项目 `tests/`；`pytest.ini` → 主项目根
3. `Dockerfile`、`docker-compose.yml` → 主项目根（`CMD uvicorn app.main:app` 与挂载的 `./data`、`./models` 在主项目均已就位，可直接用）
4. `requirements.txt` 补一行 `streamlit-autorefresh>=1.0`（解决 `app/dashboard/app.py` 无法导入的遗留问题）
5. 合并两份 `.env.example` 的键集合（15 个键的完整清单）
6. 可选：补 `docs/项目方案V1.0.md` 缺失的 2 行表格

迁移后重跑 `pytest tests/` 确认 12 项契约测试通过，即可删除目录。

### 若选择立即删除

技术上可行（无引用、无占用、后端已替代），但会**永久丢失**上述 5 项资产在工作区中的可用性 —— 需要时只能从 `~/Desktop/点时成金/forecasts for gold prices_bak0806/` 中翻找。**且因目录未被 Git 追踪，git 无法回滚。**

### 删除方式（若最终执行）

**务必使用系统废纸篓，不要用 `rm -rf`**：

```bash
osascript -e 'tell application "Finder" to delete POSIX file "/Users/echo/Desktop/forecasts for gold prices/forecasts-for-gold-prices-main"'
```

---

*本次评估全程只读，未创建、修改、移动或删除该目录内任何文件。*
