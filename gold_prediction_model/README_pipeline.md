# 黄金价格方向预测 · 端到端流程

从**行情数据采集**到**预测推理**一键打通的完整代码流程。对齐《项目方案V1.0.md》§3.3 / 9.4 / 9.5。

## 1. 架构与数据流

```
                ┌─────────────── collector.py ───────────────┐
   行情数据源 ──▶ │ SinaGoldCollector (新浪COMEX日线, 重试/缓存)  │
   (Excel样本)─▶ │ MacroCollector    (VIX/GPR/EPU/DXY/TIPS)    │
                └──────────────────────┬──────────────────────┘
                                       │ (gold_df, macro_df)
                                       ▼
                ┌─────────────── preprocess.py ──────────────┐
                │ merge → clean → handle_missing → engineer  │
                │ (特征工程复用 features.build_features)      │
                └──────────────────────┬──────────────────────┘
                                       │ features_standard.csv
                                       ▼
                ┌──────────────── model.py ─────────────────┐
                │ GoldDirectionModel                        │
                │  · fit   : purged CV 选树数 + 隔离测试评估   │
                │  · predict: 上涨概率/方向                   │
                │  · tune  : AutoML 优先级调参               │
                └──────────────────────┬──────────────────────┘
                                       ▼
                ┌────────────── pipeline.py ─────────────────┐
                │ 采集→预处理→训练/评估→预测→落盘（一键/定时） │
                └─────────────────────────────────────────────┘
```

## 2. 模块职责

| 文件 | 职责 |
|---|---|
| `collector.py` | 采集模块：黄金价格（新浪 JSONP）+ 宏观指标（Excel）；`retry()` 指数退避重试；数据合法性校验；`Scheduler` 后台定时拉取 |
| `preprocess.py` | 预处理：合并（日期对齐+前向填充）、清洗、缺失值处理（ffill/bfill/插值）、特征工程、标准 CSV 落盘 |
| `model.py` | 模型定义：LightGBM+XGBoost 加权集成（0.6/0.4）；`fit/predict/evaluate/save/load`；可选 `tune` |
| `pipeline.py` | 主流程：结构化日志、CLI、串联各环节、一键运行与定时模式 |
| `config.py` | 集中配置（路径/特征/超参/划分比例/30分钟时间语义/LLM 配置） |
| `sentiment_features.py` | LLM 新闻情感 + 鹰鸽立场特征：抽取（OpenAI/Ollama/规则降级）→ bar 对齐聚合 → 文档 §9.4 特征 |
| `features.py` / `train.py` / `evaluate.py` | 底层引擎（特征工程 / 训练 / 指标） |
| `analysis.py` / `select_model.py` | 研究期产物（消融 / 无泄露选参），非主流程必需 |

## 3. 一键运行

```bash
PY=/Users/echo/.workbuddy/binaries/python/envs/default/bin/python
cd gold_prediction_model

$PY pipeline.py                 # 全链路：采集→情感特征→预处理→训练→预测→落盘
$PY pipeline.py --mode train    # 仅训练并保存模型
$PY pipeline.py --mode predict  # 载入已训练模型做推理
$PY pipeline.py --tune          # 训练前 AutoML 调参（较慢）
$PY pipeline.py --refresh       # 强制重新拉取行情（忽略缓存）
$PY pipeline.py --no-sentiment  # 禁用 LLM 情感/鹰鸽特征（宏观-only，文档降级路径）
$PY pipeline.py --llm-provider ollama   # 用本地 Ollama 抽取情感/鹰鸽（需服务在 :11434）
$PY pipeline.py --news-dir ../data/news_scraper_output  # 指定新闻目录
$PY pipeline.py --refresh-news # 忽略情感缓存，重新构建情感特征
$PY pipeline.py --schedule --interval 86400   # 每天定时运行（Ctrl+C 退出）
```

> 黄金价格已缓存于 `data/gold_gc_daily_raw.csv`，默认离线可用；`--refresh` 重新抓取。
> 情感特征默认 `provider=rule`（关键词规则引擎，零依赖、可离线复现），自动复用
> `news_scraper_output/` 中 LLM 已分析的 `sentiment_score`，并用规则补算缺失的 `hawkish_score`。

## 4. 产出

| 文件 | 说明 |
|---|---|
| `logs/pipeline_<时间戳>.log` | 结构化运行日志（控制台+文件） |
| `data/features_standard.csv` | 标准特征底表 |
| `reports/predictions_<tag>.csv` | 全量预测（概率/类别/方向） |
| `artifacts/<tag>_*.joblib` | 序列化双模型 + 元信息 |
| `reports/pipeline_result_<tag>.json` | 运行结果汇总 |

## 5. 防泄露要点（重要）

- **标签窗口 purge**：目标看向 `t+HORIZON`，划分边界剔除 HORIZON 根 bar，杜绝前视。
- **测试集隔离**：超参/树数选择仅在开发集（前85%）purged CV 完成，测试集（后15%）仅评估一次。
- **平稳化特征**：金价 1130→5446 致绝对量纲失效，已引入 `*_z` / `*_pct` / 波动比特征。
- **早停指标**：因验证/训练先验偏移，早停改用 AUC 而非 logloss。

## 6. 已知结论（详见 `reports/模型测试报告.md`）

在严格防泄露评估下，当前 5 个日频宏观指标 + COMEX 黄金日线对「30 交易日方向」的预测力≈随机
（测试 AUC≈0.5，accuracy 低于朴素基线）。**流程本身完整可复现**，结论属数据与标签定义层面，
而非工程实现问题。

## 7. LLM 情感 / 鹰鸽特征（方案文档 §3.3 / §9.2 / §9.3 / §9.4）

- **新增输入变量**：`sentiment_score`（黄金利多/利空，LLM，∈[-1,+1]）、
  `hawkish_score`（鹰派/鸽派，∈[-1,+1]，文档：鹰派→利空黄金）、及其文档 §9.4 滚动特征
  `sentiment_mean_30` / `sentiment_max_30` / `hawkish_change`。
- **抽取链路**：`sentiment_features.NewsSentimentExtractor`
  - `provider=openai` 且配 `OPENAI_API_KEY` → 调 OpenAI 兼容接口（含 qwen-turbo）
  - `provider=ollama` → 本地 Ollama（`:11434`）
  - `provider=rule`（默认）→ 关键词规则引擎（离线、可复现），且与文档一致「LLM 超时时降级」
  - rule 模式优先复用 `news_scraper_llm` 已分析的 `sentiment_score`，仅用规则补算 `hawkish_score`
- **对齐聚合**：不规则新闻时间经 `merge_asof` 对齐到建模 bar 轴（日频近似 or 真实 30 分钟 bar），
  按 bar 聚合为水平值 + `news_count`，再交 `features.attach_sentiment_features` 计算滚动特征。
- **30 分钟目标语义**：`TARGET_HORIZON_MINUTES=30`（预测未来 30 分钟方向）、
  `DESIGN_BAR_INTERVAL_MINUTES=30`（文档设计频率）、`ACTUAL_BAR_INTERVAL_MINUTES=1440`
  （当前日频近似，按已批准决策保留 `HORIZON=30` 根 bar 作为代理跨度；接入真实 30 分钟 bar 时
  将其改为 30，`horizon_bars_for()` 自动算出前瞻 bar 数=1）。模型输出与结果 JSON 均带
  `horizon_minutes=30` 与目标说明。

> **数据覆盖诚实提示**：当前 `news_scraper_output/` 仅含 2026-07-30~08-05 共 5 个交易日的
> 新闻（80 条），全部落在测试窗口内，且这些标题多无货币政策立场措辞（`hawkish_score` 全为 0）。
> 因此情感特征在**训练分布中恒为 0**，消融显示其对测试指标贡献 `auc_delta≈0`。
> 要让情感/鹰鸽特征真正发挥增强作用，需：(1) 让新闻 + LLM 覆盖完整历史区间；
> (2) 接入含美联储讲话/利率决议的语料以激活 `hawkish_score`。架构已就绪，属数据覆盖问题。
