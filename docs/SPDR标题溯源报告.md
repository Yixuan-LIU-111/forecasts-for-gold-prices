# 新闻标题溯源报告：「SPDR黄金ETF持仓量增加2.5吨，创近一个月新高」

> 追溯目标句：`SPDR黄金ETF持仓量增加2.5吨，创近一个月新高`
> 追溯对象：news 表中 `id=4` 记录（对应 `n004`）
> 追溯结论（先给）：**该句为手工硬编码的演示种子数据，既非 LLM 生成，也非任何程序/规则模板计算得出。** 它作为静态字符串直接写在 `app/dashboard/demo_data/news.json` 中，由种子引导函数逐字读入数据库，经接口与前端原样输出。

---

## 一、链路流程图（文字形式）

```
[原始数据来源]
  app/dashboard/demo_data/news.json  (静态种子文件，手工编写)
   ├─ "title"      : "SPDR黄金ETF持仓量增加2.5吨，创近一个月新高"   ← 硬编码字符串
   ├─ "title_zh"   : "SPDR黄金ETF持仓量增加2.5吨，创近一个月新高"   ← 同上（人工录入）
   ├─ "key_sentence": "Holdings rose to 945.3 tonnes, the highest in a month."  ← 英文原文
   ├─ "topic"      : "ETF" / "source": "World Gold Council" / "sentiment": "bullish"
        │
        │  (无抓取/无爬虫/无 LLM/无计算 —— 纯静态字面量)
        ▼
[数据清洗 / 计算环节]  —— ⚠️ 不存在
   • 无持仓量时间序列拉取（代码库中无 SPDR holdings 时序计算）
   • 无「增加 X 吨」差值计算（标题中的 2.5 吨 ≠ key_sentence 的 945.3 吨，无法由源句推导）
   • 无「近一个月新高」窗口/阈值判定（无 30 日窗口比较逻辑）
        ▼
[模板拼装 / 模型调用环节]  —— ⚠️ 未触发
   • seed_news() 直接取值，不经 summarize_title / llm_summarize
   • migrate_003：因 title 含中文 → 直接 title_zh = title（跳过模型）
   • migrate_004：因 title 为中文 → `continue` 跳过（保持原样）
        ▼
[落库环节]
  app/core/seed.py :: seed_news()
   News(title=..., title_zh=..., key_sentence=..., ...)  →  INSERT INTO news
        ▼
[推送 / 输出环节]
  app/api/deps.py :: serialize_news()  →  {"title_zh": n.title_zh, ...}  (GET /api/v1/news)
        ▼
  frontend/dashboard.html :: newsLink(n)  →  渲染 n.title_zh
```

---

## 二、组件定位表

| 环节 | 文件路径 | 函数 / 类 | 行号 | 行为 |
|------|----------|-----------|------|------|
| **原始数据来源（定义句）** | `app/dashboard/demo_data/news.json` | JSON 字面量 | 55（title）、68（title_zh） | 手写静态字符串 |
| **关键句（英文源）** | `app/dashboard/demo_data/news.json` | JSON 字面量 | 64 | "Holdings rose to 945.3 tonnes, the highest in a month." |
| **入库（逐字搬运）** | `app/core/seed.py` | `seed_news(db)` | 126–135 | `title=n.get("title")`、`title_zh=n.get("title_zh") or n.get("title")`；仅当表空时执行 |
| **建列/回填（未改此行）** | `scripts/migrate_003_add_title_zh.py` | `fix_seed_json()` / `backfill_db()` | 30–33 / 73–75 | 仅对 `title_zh` 为空者填值；本行 title_zh 已有 → 跳过；DB 回填时因 title 含中文直接复制，不调模型 |
| **二次精修（跳过此行）** | `scripts/migrate_004_refine_title_zh.py` | `main()` | 32–35 | `_is_chinese(title)` 为真 → `continue`，保持原样 |
| **接口序列化（原样输出）** | `app/api/deps.py` | `serialize_news(db, limit, offset)` | 160、177 | `"title_zh": n.title_zh or n.title` |
| **前端展示（原样渲染）** | `frontend/dashboard.html` | `newsLink(n)` | 570；调用点 805、898 | 优先渲染 `n.title_zh` |
| **规则构件（存在但未被用于此行）** | `app/core/title_summary.py` | `SUBJECT_RULES` / `UNIT_MAP` / `_detect_qualifier` | 31、52、~140 | 含 "SPDR黄金ETF持仓"、"吨"、"近一个月新高" 等规则构件，但仅用于英文源规则兜底，本行走中文 verbatim 分支未触发 |

---

## 三、判断依据（证据引用）

### 判定为「非 LLM 生成」

1. **无模型调用路径触达该记录**
   - 唯一 LLM 入口：`app/core/title_summary.py :: llm_summarize()`，仅由 `summarize_title()` 调用。
   - `summarize_title()` 的调用方仅两类：
     - `scripts/migrate_003_add_title_zh.py :: backfill_db()`（第 77 行）——但**仅对非中文 title** 调用（`re.search([\u4e00-\u9fff], row.title)` 为真则直接复制，第 73–75 行）。本行 title 为中文 → 走复制分支，**未调 LLM**。
     - 采集链路（`news_collector.py` / `scheduler.py` 入库新英文新闻时）——本行是种子数据，非实时抓取。
   - `migrate_004` 对中文 title 直接 `continue`（第 33–35 行），更不可能调模型。

2. **无任何 prompt 模板产出此文本**
   - `title_summary.llm_summarize` 的 SystemMessage（约第 95–108 行）与 `sentiment.py` 的 LLM 提示词均未被本行走到。仓库内搜索不到与该句匹配的 prompt 或生成日志。

3. **实测佐证**
   - 当前数据库 `news WHERE id=4`：`title` 与 `title_zh` 完全相同，且等于 `news.json` 字面量；无 `generated_by` / `model` 等字段标记来源。

### 判定为「非程序/规则计算产出」

4. **关键数字无法由源句推导（决定性证据）**
   - 标题中的 **「2.5吨」** 在 `key_sentence` 中**并不存在**；源句给的是持仓**水平**「945.3 tonnes」，而非**增量** 2.5 吨。
   - 任何基于源文本提取数字的规则/程序，都会产出 945.3 而非 2.5。2.5 是人工自由编写、且与源句口径不一致的增量，这是**手工撰写的强特征**。

5. **无「持仓量变化 / 近一个月新高」计算逻辑**
   - 全仓库检索 `持仓量`/`2.5吨`/`近一个月`/`highest in a month`：仅出现在 `news.json`（硬编码）、`title_summary.py` 的规则**字典**（构件，非计算）、以及文档说明中。
   - 不存在 SPDR holdings 时间序列拉取、不存在「近一个月（30 日窗口）最高」比较函数。因此「近一个月新高」是语义转写（呼应 "the highest in a month"），由人写出，而非代码判定。

6. **`title_summary.py` 规则构件虽形似，但确有分支隔离**
   - 该文件有 `SUBJECT_RULES` 含 `("spdr","gold etf holdings","gold etf") → "SPDR黄金ETF持仓"`（31 行）、`UNIT_MAP` 含 `"tonnes":"吨"`（52 行）、`_detect_qualifier` 含「近一个月新高」模式（~140 行）。
   - 但这些构件**专为英文源的规则兜底**设计，且 `seed_news` / `migrate_003` / `migrate_004` 对中文 title 一律走 verbatim 复制，**从未调用** `rule_summarize` 处理本行。即"构件存在"≠"本句由构件生成"。

### 综合证据等级
- 强证据：#4（数字与源句口径冲突）、#1/#2（调用链未触达模型）、#5（无计算逻辑）。
- 结论：在**当前代码库与运行时**范围内，该句是静态手写字面量，无任何生成或计算步骤参与。

---

## 四、泛化验证（其他标题是否复用同一条链路）

代码库内新闻标题实际存在 **三条加工链路**，本句属链路 A：

| 链路 | 适用对象 | 生成方式 | 是否触发模型/规则 |
|------|----------|----------|-------------------|
| **A. 演示种子（硬编码）** | `news.json` 中全部中文 title 行（约 `n001`–`n010`，含本句 `n004`、`n005` 美联储沃勒、`n006` 中国央行增持黄金等） | 人工写入 JSON，seed 逐字搬运，迁移脚本一律跳过 | 否 |
| **B-LLM. 实时抓取→LLM** | 经 NewsAPI / `scheduler` / `collector` 入库的**英文**新闻（OPENAI_API_KEY 已配置时） | `sentiment.analyze()` → `title_summary.summarize_title()` → `llm_summarize()` | 是（LLM） |
| **B-Rule. 实时抓取→规则兜底** | 同上，但无 OPENAI_API_KEY 或 LLM 失败时 | `summarize_title()` → `rule_summarize()`（主体+动作+数值+补充重点） | 是（规则） |

**分支差异与例外**
- 链路 A 与 B 的分流判据：`migrate_003` 用「title 是否含汉字」分流（含→复制，不含→调 `summarize_title`）；`migrate_004` 用 `_is_chinese(title)` 分流（中文→跳过）。
- 链路 B 内部再以「是否配置 `OPENAI_API_KEY`」二分为 B-LLM / B-Rule。
- **例外情况**：链路 A 的中文 demo 标题即使在 B 链路的迁移脚本中运行也绝不改变 —— 这是为防止规则产物覆盖人工精品而特意设计（见 `migrate_004` 第 6–10 行注释，本句被点名列为保留范例）。
- `news.json` 中**英文** title 行（如早期自动抓取的 "Meta AI model hacking" 等）才属于链路 B，会被 `migrate_004` 重算为「Meta AI 相关动态」等规则标题。

**结论印证**：本句 `n004` 处于链路 A，是人工编写、程序仅做"搬运与展示"的演示数据；与之相对，英文抓取新闻的标题才是 LLM/规则真正生成的产物。

---

## 五、最终结论

> **「SPDR黄金ETF持仓量增加2.5吨，创近一个月新高」= 人工硬编码的演示种子标题。**
>
> - 它定义在 `app/dashboard/demo_data/news.json:55`（title）/ `:68`（title_zh），作为静态字面量存在；
> - 由 `app/core/seed.py :: seed_news()`（126–135 行）逐字写入 `news` 表；
> - 经 `migrate_003`（仅填空值）、`migrate_004`（中文标题跳过）均未被改写；
> - 由 `app/api/deps.py :: serialize_news()`（177 行）原样序列化，前端 `newsLink()`（570 行）原样渲染。
>
> 它**不是 LLM 生成**（生成链路从未触达该行，且无对应 prompt/日志），也**不是程序/规则计算**（核心数字 2.5 吨与源句 945.3 吨口径冲突、且全库无持仓量/窗口计算逻辑）。
>
> 说明边界：本报告结论严格基于**当前代码库与运行时**。若该 JSON 种子文件本身在仓库之外曾借助 LLM 辅助撰写，则属于仓库外的创作行为，代码中无任何痕迹可追溯，不在本溯源范围。
