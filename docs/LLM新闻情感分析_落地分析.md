# 「点时成金」LLM 新闻情感分析 — 落地分析说明

> 本文档基于《项目方案 V1.0》中 **F04 新闻情感分析（§3.3）**、**§9.2 LLM 情感分析模型**、**US-003（§4.1）**、**sentiment 表（§8.2）**、**错误码（§11.4）**、**非功能需求（§12）** 等章节提炼，面向开发给出可直接落地的设计说明。
>
> 配套代码归属：`app/core/sentiment.py`（架构图 §6.1）、`app/models/database.py`（ORM）、`app/models/schemas.py`（Pydantic）。

---

## 0. 功能定位（来自方案原文）

- **P0 功能 F04**，已标记 ✅ 实现，是后续时序预测模型（F07）的「情感特征」输入源（§9.4 特征工程 `sentiment_mean_30` / `sentiment_max_30`）。
- **核心价值（§17.1）**：LLM 情感分数不是独立信号，而是作为 LightGBM/XGBoost 的**特征输入**，实现「语义理解 → 量化预测」深度融合。
- **设计基线**：`LangChain ChatOpenAI + PromptTemplate`，模型 `GPT-4o-mini`（性价比最高，调用目标 < 500ms，§12.1）。

---

## 1. 输入：新闻数据格式与来源

### 1.1 数据来源

| 项 | 说明 |
|----|------|
| 上游来源 | F01 新闻数据采集（NewsAPI 免费层，GNews 备选），每分钟轮询，关键词过滤 `gold / XAU / Fed / interest rate / inflation / geopolitical` |
| 落库位置 | PostgreSQL `news` 表（§8.2） |
| 触发方式 | 信号生成器每 5 分钟触发时（§10.1 第 2 步），仅对**新入库且无 sentiment 记录**的新闻做 LLM 解析，已分析过的跳过（缓存） |

### 1.2 输入字段（取自 `news` 表，经数据清洗后）

| 字段 | 类型 | 用途 | 进入 LLM 的方式 |
|------|------|------|----------------|
| `title` | TEXT | 新闻标题 | 作为 LLM 输入主内容 |
| `content` | TEXT | 正文摘要（F01 采集的是「正文摘要」而非全文） | 作为 LLM 输入主内容 |
| `source` | VARCHAR(100) | 来源媒体 | 仅落库/溯源，不参与打分 |
| `url` | TEXT (UNIQUE) | 原文链接 | 去重键 + 溯源引用 |
| `published_at` | TIMESTAMPTZ | 发布时间 | 时效加权参考（可选） |

> **输入契约**：实际送进 LLM 的只有 **标题 + 正文摘要**（§3.3「输入：新闻标题 + 正文摘要」）。`content` 为空时降级为仅用 `title`。

### 1.3 Pydantic 输入模型（建议，遵循 MCP 指南的输入约束）

```python
from pydantic import BaseModel, Field

class NewsInput(BaseModel):
    news_id: int                       # 关联 news.id，用于落库外键
    title: str = Field(..., min_length=1, max_length=500,
                       description="新闻标题，必填")
    content: str | None = Field(default=None, max_length=4000,
                                description="正文摘要，可为空，空时仅用标题")
    url: str | None = Field(default=None, description="原文链接，用于溯源")
```

---

## 2. LLM 调用：接口与参数配置

### 2.1 调用栈（原文指定）

`LangChain PromptTemplate → ChatOpenAI(GPT-4o-mini) → StrOutputParser → Pydantic 解析`（§3.3、§9.2）。

### 2.2 推荐参数配置

| 参数 | 建议值 | 依据 / 说明 |
|------|--------|------------|
| `model` | `gpt-4o-mini` | §3.3 / §7.2 指定，成本约 $0.15 / 1M tokens（§18.4） |
| `temperature` | **0** | 情感打分需确定性、可复现，不可用随机采样 |
| `max_tokens` | 300–500 | 输出为单条 JSON，无需长文本 |
| `timeout` | 10s（方案目标 < 500ms，超 10s 视为超时触发降级） | §12.1、§11.4 错误码 3001 |
| `response_format` | JSON / 结构化输出 | 配合 Pydantic 解析，降低格式异常率 |
| `max_retries`（SDK 层） | 2 | 叠加 12.3 指数退避策略 |
| 并发 | 单进程，受每日成本上限约束 | §12.4 每日 $5 上限 |

### 2.3 配置管理（pydantic-settings，§7.2 / §13.2）

环境变量（`.env`，经 `docker-compose` 注入）：

```env
OPENAI_API_KEY=sk-xxxx                    # 必填（§13.2）
OPENAI_MODEL=gpt-4o-mini
OPENAI_TEMPERATURE=0
OPENAI_TIMEOUT=10
OPENAI_MAX_RETRIES=2
LLM_DAILY_COST_CAP_USD=5                  # §12.4 成本上限
LLM_RULE_FALLBACK=true                    # LLM 不可用时降级开关
```

```python
# app/config.py（节选）
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    openai_api_key: str
    openai_model: str = "gpt-4o-mini"
    openai_temperature: float = 0.0
    openai_timeout: int = 10
    openai_max_retries: int = 2
    llm_daily_cost_cap_usd: float = 5.0

    class Config:
        env_file = ".env"
```

---

## 3. 情感分数定义与输出结构

### 3.1 输出字段（严格对应 §3.3 输出表）

| 字段 | 类型 | 范围 | 含义 |
|------|------|------|------|
| `sentiment_score` | float | **-1 ~ +1** | 情感分数（-1 强烈利空，+1 强烈利多） |
| `topic` | string | 枚举（见下） | 主题标签 |
| `confidence` | float | **0 ~ 1** | 模型置信度 |
| `key_sentence` | string | 自由文本 | 影响判断的关键句（用于引用溯源） |

### 3.2 标签体系（topic 枚举，来自 §9.2 System Prompt）

```
Fed | Inflation | Geopolitical | Dollar | Other
```

> 即：美联储 / 通胀 / 地缘政治 / 美元 / 其他。落库列 `topic VARCHAR(50)`（§8.2）。

### 3.3 衍生方向标签（方案未显式定义阈值，以下为推荐落地约定）

仪表盘展示使用 🟢利多 / 🔴利空 / ⚪中性三色（§10.2），需由连续分数映射为离散标签：

| `sentiment_score` | 方向标签 | 展示颜色 | 说明 |
|:----------------:|:--------:|:--------:|------|
| `> +0.15` | 利多 (bullish) | 🟢 绿 | 正向偏强 |
| `(-0.15, +0.15]` | 中性 (neutral) | ⚪ 灰 | 影响不显著（阈值可按回测调优） |
| `<= -0.15` | 利空 (bearish) | 🔴 红 | 负向偏强 |

> 注：方案原文只在「黄金多空评分（§10.4）」与「信号方向」处给出阈值，情感本身的 neutral 切割点方案未写死，此处给出**推荐默认值**，开发时作为可配置项，便于人工抽检（§12.2 一致率 > 85%）调参。

### 3.4 Pydantic 输出模型（结构化解析，§9.2「StrOutputParser + Pydantic」）

```python
from pydantic import BaseModel, Field, field_validator
from typing import Literal

class SentimentOutput(BaseModel):
    sentiment_score: float = Field(..., ge=-1.0, le=1.0,
        description="-1 强烈利空 ~ +1 强烈利多")
    topic: Literal["Fed", "Inflation", "Geopolitical", "Dollar", "Other"]
    confidence: float = Field(..., ge=0.0, le=1.0)
    key_sentence: str = Field(..., max_length=500)

    @field_validator("sentiment_score")
    @classmethod
    def round_score(cls, v):
        return round(v, 3)   # 对应 DECIMAL(4,3)
```

---

## 4. 解析流程步骤划分

对齐 §10.1 信号生成第 2 步 + §9.2 输出解析，单条新闻处理流程如下：

```
┌─────────────────────────────────────────────────────────────┐
│ Step 1  取数                                                 │
│   从 news 表取「新入库且 sentiment 表无对应 news_id」的新闻   │
│   （news.url UNIQUE + sentiment.news_id FK 去重，§8.3）        │
├─────────────────────────────────────────────────────────────┤
│ Step 2  组装 Prompt                                         │
│   System Prompt（§9.2 规则）+ Few-shot（3-5 条，§9.2 表）    │
│   + 黄金领域同义词库注入（§9.2 同义词表）                     │
│   + 当前新闻 {title, content}                               │
├─────────────────────────────────────────────────────────────┤
│ Step 3  调用 LLM                                            │
│   ChatOpenAI → StrOutputParser → 绑定 SentimentOutput       │
│   超时/限流按 §6 重试与降级                                  │
├─────────────────────────────────────────────────────────────┤
│ Step 4  结构化解析                                          │
│   Pydantic 校验字段类型与范围；失败记 3002 → 重试 1 次        │
├─────────────────────────────────────────────────────────────┤
│ Step 5  结果校验                                            │
│   score ∈ [-1,1]、confidence ∈ [0,1]、topic ∈ 枚举；         │
│   超界则 clamp 或标记低置信度（§12.3）                       │
├─────────────────────────────────────────────────────────────┤
│ Step 6  落库                                                 │
│   写入 sentiment 表，news_id 外键关联（§8.2）                 │
├─────────────────────────────────────────────────────────────┤
│ Step 7  降级兜底（仅异常分支）                               │
│   LLM 超时/额度耗尽/格式异常 → 规则引擎（关键词匹配）         │
│   结果标记 low_confidence=True，sentiment 表可加标志位        │
└─────────────────────────────────────────────────────────────┘
```

---

## 5. 错误处理与重试机制

### 5.1 错误码映射（§11.4）

| 错误码 | 含义 | 处理 |
|--------|------|------|
| **3001** | LLM API 超时 | 指数退避重试 → 仍失败则降级规则引擎 |
| **3002** | LLM 返回格式异常 | Pydantic 解析失败，重试 1 次 → 降级规则引擎 |
| **4001** | OpenAI API 额度耗尽 | 当日停止 LLM 调用，全局降级规则引擎（§12.2 日费用 > $5 自动停止） |

### 5.2 重试策略（结合 §12.3 + §12.4）

| 异常类型 | 策略 |
|----------|------|
| 网络超时（timeout 10s） | 重试 ≤ 2 次，间隔指数退避（1s, 2s） |
| HTTP 429 限流 | 读取 `Retry-After`，指数退避重试；NewsAPI 免费层 100 次/天需合并请求 |
| HTTP 5xx | 指数退避重试 ≤ 2 次 |
| 4001 额度耗尽 | **不重试**，直接全局降级 + 告警（§15.2） |
| 格式异常 3002 | 重试 1 次；仍失败 → 降级规则引擎 |

> 与数据采集层一致：方案 §12.3 规定 `httpx + 指数退避重试（3 次）`，LLM 层可复用同一退避工具类。

### 5.3 降级策略（§4.1 US-003 / §12.3 / §10.1）

- **规则引擎（关键词匹配）**：使用 §9.2 黄金领域同义词库（加息/降息/量化宽松/避险/通胀等）做正向/负向词命中计数，输出 `sentiment_score` 与 `topic`，`confidence` 置为低值（如 0.3）并标记 `low_confidence`。
- **信号侧影响**：信号生成器「降级策略」规定 LLM 不可用时仅用量化模型，置信度 < 0.55 输出「观望」（§10.1）。

---

## 6. 结果校验与落库方式

### 6.1 校验规则

1. **结构校验**：`SentimentOutput` Pydantic 模型约束类型与范围（§3.4）。
2. **语义校验**：
   - `sentiment_score` 越界 → `round/clamp` 到 [-1, 1] 并记录 warning；
   - `confidence` 越界 → clamp 到 [0, 1]；
   - `topic` 不在枚举 → 归为 `Other`。
3. **一致性校验（§8.3）**：情感结果与 `news_id` 外键约束，保证每条新闻至多一条情感记录（去重）。

### 6.2 落库（ORM，对应 §8.2 `sentiment` 表）

```sql
-- 建表（§8.2 原文）
CREATE TABLE sentiment (
    id            BIGSERIAL PRIMARY KEY,
    news_id       BIGINT REFERENCES news(id),
    score         DECIMAL(4,3),           -- -1.000 ~ +1.000
    topic         VARCHAR(50),            -- Fed, Inflation, Geopolitical
    confidence    DECIMAL(3,2),           -- 0.00 ~ 1.00
    key_sentence  TEXT,                   -- 归因引用
    created_at    TIMESTAMPTZ DEFAULT NOW()
);
```

```python
# app/models/database.py（节选）
from sqlalchemy import Column, BigInteger, Numeric, String, Text, TIMESTAMP
from sqlalchemy.dialects.postgresql import BIGSERIAL
from .database import Base

class Sentiment(Base):
    __tablename__ = "sentiment"
    id = Column(BIGSERIAL, primary_key=True)
    news_id = Column(BigInteger, nullable=False)        # 建议加 ForeignKey + Unique
    score = Column(Numeric(4, 3))
    topic = Column(String(50))
    confidence = Column(Numeric(3, 2))
    key_sentence = Column(Text)
    created_at = Column(TIMESTAMP(timezone=True), server_default="now()")
```

> **关键约束（§8.3）**：`news_id` 应加唯一约束以实现「相同新闻缓存情感结果（URL 去重）」（§12.4），避免重复 LLM 调用与成本浪费。

### 6.3 下游消费

- 特征工程（§9.4）：`sentiment_mean_30 = sentiment_score.rolling(30).mean()`、`sentiment_max_30`。
- 仪表盘（§10.2）：`GET /api/news/latest` 返回最新新闻 + 情感标签（🟢/🔴/⚪）。
- 信号归因（§10.5）：通过 `news_refs` 引用 `key_sentence` + `url` 实现溯源。

---

## 7. 依赖与环境配置

### 7.1 运行时依赖（取自 §18.1 requirements.txt）

```
langchain>=0.1
langchain-openai>=0.1
openai>=1.0            # ChatOpenAI 底层
pydantic>=2.0
pydantic-settings>=2.0
sqlalchemy>=2.0
psycopg2-binary>=2.9   # PostgreSQL 驱动
httpx>=0.27            # 异步调用 + 退避重试
```

### 7.2 环境变量（§13.2 docker-compose + §18.4）

| 变量 | 必填 | 说明 |
|------|------|------|
| `OPENAI_API_KEY` | 是 | LLM 服务鉴权 |
| `NEWSAPI_KEY` | 是 | 上游新闻数据（F01） |
| `DATABASE_URL` | 是 | `postgresql://gold:gold@db:5432/gold_predictor` |
| `LLM_DAILY_COST_CAP_USD` | 建议 | §12.4 成本熔断 |

### 7.3 部署形态（§13）

- Docker Compose 双容器：`app`（FastAPI + Streamlit + 业务模块）与 `db`（PostgreSQL 16）。
- LLM 计算在云端，本地容器仅 ~50–100MB 内存占用（§13.6）。
- 启动：`docker compose up -d` → 自动 `init_db()` 建表（§13.4）。

---

## 8. 验收与质量门槛（对应 §16）

| 维度 | 标准 |
|------|------|
| 功能（§16.1） | 每条新闻输出 `sentiment_score`、`topic`、`confidence` |
| 一致性（§12.2） | 人工抽检 50 条，LLM 与人工一致率 > 85% |
| 性能（§12.1） | 单条 LLM 调用 < 500ms |
| 稳定性（§12.3） | LLM 超时/异常均降级规则引擎，信号标记低置信度 |
| 成本（§12.4） | 每日 OpenAI 费用 ≤ $5，相同新闻缓存 |

---

## 9. 附：按 MCP 规范封装为工具（呼应《MCP 开发指南》）

> 若后续希望将此能力以 **MCP Server** 形式对外提供（供其他 Agent 调用），可将其封装为一个符合 MCP 最佳实践的 Tool。以下为按《MCP 开发指南》的规格建议。

**Tool 命名（一致前缀）**：`gold_analyze_news_sentiment`

**Input Schema（Zod/Pydantic，含约束与示例）**
```json
{
  "news_id": "integer (required)",
  "title": "string (1-500, required)",
  "content": "string? (<=4000)",
  "url": "string?"
}
```

**Output Schema（structuredContent）**
```json
{
  "sentiment_score": "number [-1,1]",
  "topic": "enum[Fed,Inflation,Geopolitical,Dollar,Other]",
  "confidence": "number [0,1]",
  "key_sentence": "string",
  "low_confidence": "boolean   // 是否由规则引擎降级产生"
}
```

**Tool 描述（actionable）**
> "对单条黄金相关新闻做 LLM 情感分析，返回 [-1,1] 情感分数、主题标签、置信度与关键句；LLM 不可用时自动降级为关键词规则引擎并标记 low_confidence。"

**Annotations**
```json
{ "readOnlyHint": true, "destructiveHint": false,
  "idempotentHint": true, "openWorldHint": false }
```
（读新闻、写自身 sentiment 记录、幂等于 news_id，故 `idempotentHint=true`。）

**错误返回（可操作信息）**
- 3001：返回「LLM 超时，已降级规则引擎，请稍后重试或检查 OPENAI_API_KEY」。
- 4001：返回「OpenAI 额度耗尽，今日已熔断，请明日或充值后重试」。

---

## 10. 落地清单（开发自查）

- [ ] `app/core/sentiment.py`：实现 Step1–7 流程 + 规则引擎降级分支
- [ ] `app/models/schemas.py`：`NewsInput` / `SentimentOutput` Pydantic 模型
- [ ] `app/models/database.py`：`Sentiment` ORM，含 `news_id` 唯一约束
- [ ] `app/config.py`：OpenAI / 重试 / 成本上限配置项
- [ ] 退避重试工具类（复用数据采集层的 httpx 退避）
- [ ] Few-shot 示例 3–5 条 + 黄金同义词库注入 Prompt
- [ ] 仪表盘 `GET /api/news/latest` 情感标签（🟢/🔴/⚪）联调
- [ ] 每日成本熔断（$5）与额度耗尽（4001）全局降级开关
- [ ] 人工抽检脚本（周抽 50 条，一致率 > 85% 监控）

---

*文档依据：《项目方案 V1.0》F04 / §3.3 / §8.2 / §9.2 / §10.1 / §11.4 / §12 / §16 / §18；MCP 封装建议参考《MCP 开发指南》。*
