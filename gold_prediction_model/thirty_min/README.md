# 黄金 30 分钟预测模型（thirty_min）

整合 **LLM 新闻情感分析模块**（`news_scraper_llm`）与 **XAU/USD 30 分钟行情获取**（`xauusd_30m_scraper`），
完成「数据对齐 → 特征工程 → 集成训练 → 评估消融 → 推理」全链路。

> 对应《项目方案V2.0.md》§3.5、§4.2（Phase 2：Predictor 30min + 情感消融 C-8）。

---

## 项目硬约束（不可变更）

两项约束见方案 §0.1，本包所有周期/窗口参数均显式绑定 30 分钟：

| 约束 | 取值 | 说明 |
|------|------|------|
| 预测窗口 | `HORIZON_MINUTES=30` / `PREDICT_WINDOW="30min"` | 固定未来 30 分钟，不退化到日频 |
| 配色 | 涨=红 / 跌=绿 | 由前端/可视化层统一处理，本包只产出「方向 + 概率」，不携带颜色 |

---

## 模块布局

```
gold_prediction_model/thirty_min/
├── config.py          # 统一配置入口（唯一）。路径、窗口、特征分组、超参、阈值
├── logging_setup.py   # get_logger()：控制台 + logs/thirty_min.log 双输出
├── data_layer.py      # 需求1：30min K线 + 新闻情感 + 宏观因子 按时间对齐
├── features.py        # 需求2：技术 + 情感聚合 + 市场因子特征
├── model.py           # 需求3：LightGBM+XGBoost 加权集成 + Predictor 推理封装
├── evaluate.py        # 需求4：时序划分 / 指标 / 收益回撤 / 情感消融
├── sample_data.py     # 合成数据生成器（真实数据不足时驱动示例入口）
├── run_pipeline.py    # 需求5：可运行示例入口（CLI）
├── artifacts/         # 训练产物 *.joblib（模型 + meta）
├── reports/           # eval_report_*.json（评估 + 消融报告）
└── logs/              # thirty_min.log
```

所有子模块**仅用相对导入**（`from . import config`），与旧日频模块顶层的 `import config` 解耦，规避导入冲突。

---

## 需求落地对照

### 需求1 · 数据层（data_layer.py）
- **30 分钟 K 线**：读取 `xauusd_30m_scraper` 落盘的 `data/xauusd_30m_bars.jsonl` + `data/xauusd_30m_latest_bar.json`（OHLC、成交量、时间戳）。
- **新闻情感**：解析 `news_scraper_llm` 输出的 `data/news_scraper_output/news_sentiment_*.json`，字段 `sentiment_score(-1~1)`、`confidence(0~1)`、`news_time`。
- **宏观因子**：DXY / VIX / TIPS / GPR / EPU / USD 指数，读 `data/*.json(l)`。
- **时区**：统一北京时间（`Asia/Shanghai`），`_to_naive_ts()` 归一化 tz-aware/tz-naive 时间戳。
- **缺失值**：因子 `reindex + ffill + bfill`；情感窗口内无新闻则填 0。
- **新闻滞后（前视安全）**：新闻事件归入「≤ 事件时刻」的最新 bar（`searchsorted(side="right")-1`）；日频因子视为当日 23:30 后才生效再 ffill。
- **目标变量**：`target = close.shift(-1) > close`（未来 1 根 30min bar 是否上涨），无前视泄漏。

### 需求2 · 特征工程（features.py）
- 技术：`ret_1`、`log_ret`、`ret_vol`、`ma_dev`、`range_pct`
- **情感聚合**（窗口 `SENTIMENT_WINDOW_BARS=20`）：`sent_mean`、`sent_absmax`、`sent_std`、`news_density`、`sent_conf_mean`、`has_news`
- 市场因子：`dxy_return`、`vix_level`、`vix_change`、`tips_change`、`gpr_level`、`epu_level`
- `make_xy()` 自动丢弃全 NaN 特征列（兼容真实/合成环境），再 `dropna`。

### 需求3 · 模型层（model.py）
- 双模型 **LightGBM + XGBoost** 加权集成：`p = 0.6·p_lgb + 0.4·p_xgb`（方案 §9.4）。
- **早停指标改用 AUC**（对正负先验偏移不敏感，避免 logloss 早停退化为 `best_iteration=1`）。
- `Predictor.fit / predict_proba / predict_direction`：输入一行特征 → 输出
  `{direction(涨/跌/观望), direction_en, probability, confidence(|p-0.5|*2), bull_bear_score, model, predict_window:"30min", horizon_minutes:30}`。
- 可序列化：`save(tag)` / `Predictor.load(tag)`。

### 需求4 · 评估与消融（evaluate.py）
- **时序划分** 70/15/15（`chronological_split`），含 López de Prado **Purge**（`PURGE_BARS=1`）切断标签窗口重叠。
- 指标：`compute_metrics`（AUC / Acc / F1 / Precision / Recall / LogLoss）、`baseline_metrics`（majority / always_up / prior）。
- **收益回撤**：`profit_drawdown()` 按阈值生成多空信号，对比策略累计收益与买入持有、最大回撤。
- **情感消融** `run_ablation()`：同一数据分别训练「含情感 / 不含情感」，对比 ΔAUC / ΔAcc，给出结论文本。

### 需求5 · 工程（解耦 + 配置 + 日志 + 示例）
- 配置单一入口 `config.py`；日志统一 `logging_setup.get_logger`。
- 示例入口 `run_pipeline.py`，解耦读取上游落盘文件（**不 import** `news_scraper_llm` / `xauusd_30m_scraper`）。

---

## 运行方式

从**仓库根目录** `forecasts for gold prices` 以 `-m` 执行（使用项目自带 venv）：

```bash
# 1) 自动：真实数据 ≥200 根则训练真实数据；否则回退合成数据演示
news_scraper_llm/.venv/bin/python3 -m gold_prediction_model.thirty_min.run_pipeline

# 2) 强制合成数据演示
news_scraper_llm/.venv/bin/python3 -m gold_prediction_model.thirty_min.run_pipeline --use-synthetic

# 3) 仅推理最新一根 30 分钟 bar（无模型则先训练）
news_scraper_llm/.venv/bin/python3 -m gold_prediction_model.thirty_min.run_pipeline --predict
```

> 依赖：`lightgbm`、`xgboost`、`scikit-learn`、`pandas`、`joblib`（项目 venv 已装）。

输出：
- `artifacts/primary_{lgb,xgb,meta}.joblib`
- `reports/eval_report_YYYYMMDD_HHMMSS.json`
- 控制台 + `logs/thirty_min.log` 完整日志

---

## 合成数据回退设计（sample_data.py）

真实 30 分钟历史仅 1 根（新浪历史 K 线接口已停用，仅实时报价可聚合），不足以训练。
`build_model_table(use_synthetic_fallback=True)` 在真实 bar < `MIN_BARS_FOR_TRAIN=200` 时：

1. 用可复现种子（`seed=42`，起始 `2026-07-01 09:00`）生成 GBM 价格（**无漂移**，隔离动量，使技术面无法套利）。
2. 引入潜在情感状态 `s_t ~ AR(1)`，**因果**驱动下一根收益：`signal[1:] = beta · s[:-1]`（`beta=0.0022`）。
3. 新闻分数 = `s + 噪声`，使「含情感」模型存在可学习增量信号。

目的：让示例入口今天就能端到端跑通，并验证**情感消融方法论**（而非声称某固定 Δ 符号）。结论中「情感增量有限」为诚实结论，效果优化列为独立研究议题。

---

## 与上游的对接点（契约）

| 本包读取 | 上游模块 | 文件契约 |
|----------|----------|----------|
| 30min K线 | `xauusd_30m_scraper` | `data/xauusd_30m_bars.jsonl`、`data/xauusd_30m_latest_bar.json` |
| 新闻情感 | `news_scraper_llm` | `data/news_scraper_output/news_sentiment_*.json` |
| 宏观因子 | `dxy/vix/tips/gpr/epu` 各 scraper | `data/*.json(l)` |

本包只依赖**文件落盘契约**，不 import 上游代码，保证模块解耦与独立演进。
