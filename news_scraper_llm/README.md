# news_scraper_llm — 多站点新闻抓取 + LLM 情感分析

抓取美联储、白宫、AP News、CNN International 的最新新闻，使用阿里云百炼免费模型 **qwen-turbo**（OpenAI 兼容）进行情感分析，输出 JSON/CSV 结构化结果。

## 目标提取位置

抓取字段与截图红框对应关系（详见 `docs/news_sample/`）：

| 站点 | 截图 | 红框目标区域 | 提取字段 |
|------|------|--------------|----------|
| Federal Reserve | `www.federalreserve.gov:newsevents.htm.png` | Press Releases / Speeches / Testimony 列表 | title, url, published_at, category, summary* |
| White House | `www.whitehouse.gov:news.png` | /news/ 新闻卡片列表 | title, url, published_at, category, summary* |
| AP News | `apnews.com.png` | 首页 Hero 头条 + More Coverage | title, url, category, summary（列表页有描述时） |
| CNN International | `edition.cnn.com.png` | 首页头条及次要标题 | title, url, category, summary* |

> `summary*`：列表页通常仅展示标题，开启 `FETCH_ARTICLE_SUMMARIES=true` 后会进入详情页提取首段/meta description。

## 处理流程

```
抓取（Playwright） → 解析（站点特定 CSS Selector） → LLM 情感分析（LangChain + qwen-turbo，JSON mode 结构化输出 + 手动解析兜底） → 保存 JSON/CSV
```

## 快速开始

> **环境要求**：Python **≥ 3.10**（本项目用到 `str | None` 语法与 langchain）。
> 仓库已内置一个 Python 3.13 的虚拟环境 `news_scraper_llm/.venv`，并装好了 langchain / openai / pydantic / pandas 等全部依赖；**只需再补装 Playwright 及其浏览器**即可（见步骤 1）。

### 1. 安装 Playwright（仅需做一次）

```bash
cd "/Users/echo/Desktop/forecasts for gold prices/news_scraper_llm"

# 用仓库自带的 venv 安装 playwright（你的本机内存充足，可正常下载）
.venv/bin/pip install playwright

# 下载 Chromium 浏览器（约 150MB，只需一次）
.venv/bin/python -m playwright install chromium
```

> 如果你本机另有 Python ≥ 3.10 的 venv，也可以 `pip install -r requirements.txt && playwright install chromium`，效果相同。

### 2. 配置 API Key

```bash
cd "/Users/echo/Desktop/forecasts for gold prices/news_scraper_llm"
cp .env.example .env          # 已默认配好 qwen-turbo + 阿里云端点
# 编辑 .env，把 OPENAI_API_KEY 改成你的阿里云百炼 key（也可 export OPENAI_API_KEY=...）
```

### 3. 运行（务必从父目录执行）

```bash
# 进入【父目录】 forecasts for gold prices（不是 news_scraper_llm 内部）
cd "/Users/echo/Desktop/forecasts for gold prices"

news_scraper_llm/.venv/bin/python -m news_scraper_llm
```

或使用激活方式（同样在父目录执行）：

```bash
source news_scraper_llm/.venv/bin/activate
python -m news_scraper_llm
```

> ⚠️ 不要在 `news_scraper_llm/` 目录内部执行 `python -m news_scraper_llm`，否则会报
> `No module named news_scraper_llm`。也从不要使用系统自带的 Anaconda `python3`（它是 3.6.5，太旧）。

结果保存在 `data/news_scraper_output/`：
- `news_sentiment_YYYYMMDD_HHMMSS.json`
- `news_sentiment_YYYYMMDD_HHMMSS.csv`

## 输出字段

| 字段 | 说明 |
|------|------|
| `source` | 来源站点 |
| `title` | 新闻标题 |
| `url` | 原文链接 |
| `published_at` | 发布时间（原始字符串，部分站点可能为空） |
| `category` | 栏目/分类 |
| `summary` | 正文摘要（默认来自列表页；开启 `FETCH_ARTICLE_SUMMARIES=true` 则从详情页补充） |
| `sentiment_score` | 情感分值 -1 ~ +1 |
| `sentiment_label` | `positive` / `negative` / `neutral` |
| `topic` | LLM 提取的主题标签 |
| `confidence` | LLM 置信度 0 ~ 1 |
| `key_sentence` | 支撑判断的关键句 |
| `scraped_at` / `analyzed_at` | 抓取/分析时间 |

### 情感标签阈值（默认）

- `positive`：score > 0.15
- `neutral`：-0.15 ≤ score ≤ 0.15
- `negative`：score < -0.15

> 阈值在 LLM prompt 中定义，修改 `analyzer.py` 中的 `_GENERAL_SYSTEM` / `_GOLD_SYSTEM` 即可调整。

## 两种情感模式

通过 `.env` 中的 `SENTIMENT_MODE` 切换：

- `general`：通用新闻正/负/中，topic 如 Politics, Economy, Military
- `gold`：针对黄金价格影响的利多/利空，topic 如 Fed, Inflation, Geopolitical, Dollar（复用《项目方案 V1.0》§9.2 规则）

## 可选：作为 MCP Server 使用

```bash
pip install mcp
python news_scraper_llm/mcp_server.py
```

提供 Tool：`scrape_news_sentiment(sites, max_items_per_site, sentiment_mode)`。

## 注意事项

1. **CSS Selector 可能随网站改版失效**：站点改版后需在 `scrapers/<site>.py` 中更新选择器。
2. **遵守 robots.txt 与使用条款**：本程序仅供学习和研究使用，请合理控制抓取频率（`POLITE_DELAY_MS`）。
3. **正文摘要**：列表页未提供摘要时，可开启 `FETCH_ARTICLE_SUMMARIES=true` 进入详情页提取，但会增加请求量和运行时间。
4. **LLM 成本**：默认使用阿里云百炼 **qwen-turbo 免费模型**（每月 100 万 token 免费额度），零成本；抓取条数由 `MAX_ITEMS_PER_SITE` 控制。如需更强能力可改 `OPENAI_MODEL`（如 qwen-plus），将转为按量计费。
5. **兼容性与降级**：`analyzer.py` 优先用 `with_structured_output(method="json_mode")` 获取结构化结果；若端点/模型不支持结构化输出，会自动回退到「普通文本链 + 自行解析 JSON」；任何异常（网络/超时/鉴权/解析失败）均降级为「中性·低置信」，保证流水线不中断。
5. **无头模式**：本地调试可设 `HEADLESS=false` 观察浏览器行为。

## 与「点时成金」项目集成

`AnalyzedNewsItem.to_dashboard_dict()` 可输出仪表盘 `news_list` 组件所需的字段格式，方便直接接入 `app/dashboard/components/news_list.py`。
