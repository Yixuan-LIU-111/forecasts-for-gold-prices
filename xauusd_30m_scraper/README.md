# XAU/USD 30 分钟行情获取模块（数据源：新浪财经）

获取现货黄金/美元（XAU/USD，伦敦金）**30 分钟周期**的行情数据，输出结构化
`timestamp / open / high / low / close` K 线，供「点时成金」项目下游模型与仪表盘使用。

## 核心约束（项目级，不可变更）

- **预测 / 行情窗口固定为 30 分钟**：所有接口、字段、参数命名均围绕
  `HORIZON_MINUTES=30` / `PREDICT_WINDOW="30min"` / `INTERVAL_LABEL="30min"` 展开，
  不调整为其他周期。
- **配色**：行情本身的涨跌在 UI 层遵循项目统一「涨红跌绿」规则（见 `docs/项目方案V2.0.md` §0.1）。

## 数据源与方案说明

- 实时报价接口：`https://hq.sinajs.cn/list=hf_XAU`（新浪「伦敦现货黄金」代码 `hf_XAU`），
  已验证稳定可用，需带 `Referer: https://finance.sina.com.cn`，否则返回空。
- **重要**：新浪面向公众的「历史 / 分时 K 线」JSONP 接口
  （`shd2/getkline`、`forex/kline`、`rshq/kline` 等）当前已全部返回
  `Invalid service name` 已下线。因此本模块采用
  **「定时拉取实时报价 → 按 30 分钟边界聚合为 OHLC K 线」** 的方式提供数据，
  既满足方案「最新 K 线或报价数据」的要求，又完全基于新浪数据源。
- 若新浪后续恢复 K 线接口，只需在 `config.py` 调整 `SINA_QUOTE_URL` 并扩展
  `parser.py` 的解析分支，聚合 / 落盘 / 调度逻辑无需改动。

## 目录结构

```
xauusd_30m_scraper/
├── __init__.py      # 包说明与约束
├── config.py        # URL / 请求头 / 重试 / 30分钟窗口 / 落盘路径
├── errors.py        # FetchError / ParseError / AggregatorError
├── client.py        # HTTP 客户端：超时 + 指数退避重试 + 异常捕获
├── parser.py        # 解析 hq.sinajs.cn 行情串 → 结构化 Quote
├── models.py        # Quote / Bar 数据模型（dataclass，零依赖）
├── aggregator.py    # 30 分钟 K 线聚合（按北京时间对齐窗口）
├── storage.py       # 落盘：最新报价 / 最新 bar / 历史 JSONL
├── scheduler.py     # run_once() + Scheduler.run() 定时循环（优雅退出）
└── main.py          # CLI 入口
```

## 依赖

仅 Python 标准库（`urllib`、`json`、`logging`、`argparse`、`signal`、`dataclasses` 等），
无需安装第三方包。

## 使用方式（请以模块方式执行，便于相对导入）

```bash
# 单次拉取并落盘（默认）
python -m xauusd_30m_scraper.main --once

# 单次拉取但不落盘（调试）
python -m xauusd_30m_scraper.main --once --dry-run

# 定时循环拉取（Ctrl+C 或 SIGTERM 优雅退出）
python -m xauusd_30m_scraper.main --serve
python -m xauusd_30m_scraper.main --serve --interval 15   # 每 15 秒拉一次

# 查看最近 N 根已闭合 K 线
python -m xauusd_30m_scraper.main --once --show-bars --count 10
```

## 输出文件（位于 `data/`）

| 文件 | 内容 | 写入方式 |
|------|------|----------|
| `xauusd_30m_latest_quote.json` | 最新一笔实时报价（全字段） | 覆盖写 |
| `xauusd_30m_latest_bar.json`   | 当前 forming / 最近一根 30 分钟 bar | 覆盖写 |
| `xauusd_30m_bars.jsonl`        | 已闭合的 30 分钟 K 线历史 | 追加写 |

## 数据结构

**Quote（实时报价）**

| 字段 | 说明 |
|------|------|
| `symbol` / `series_name` | `hf_XAU` / 伦敦现货黄金 (XAU/USD) |
| `timestamp` | 报价时间（北京时间 `YYYY-MM-DDTHH:MM:SS`） |
| `last` | 最新价（K 线聚合的主价格） |
| `bid` / `ask` | 买卖价（参考；新浪现货行情串买价不可靠，置空） |
| `open` / `high` / `low` / `prev_close` | 行情串提供的当日开/高/低/昨收（参考，可能内部不一致） |
| `raw` | 原始数值字段列表（排查用） |

**Bar（30 分钟 K 线）**

| 字段 | 说明 |
|------|------|
| `timestamp` | 窗口起始时间（北京时间，对齐到 30 分钟边界） |
| `open` | 窗口内首笔价格 |
| `high` / `low` | 窗口内最高 / 最低 |
| `close` | 窗口内最新价格 |
| `count` | 窗口内采样点数 |
| `window` | 固定 `"30min"` |
| `completed` | 窗口是否已闭合 |

> 说明：30 分钟 K 线的权威 OHLC 由聚合器基于 `last` 采样生成，不依赖行情串中可能
> 不一致的 `high/low` 字段；当前 forming bar 在窗口内 `open==high==low==close`（随采样扩展）。

## 健壮性

- **重试**：`client.fetch_quote_raw` 对 HTTP 错误 / 网络错误 / 超时 / 空响应做
  指数退避重试（最多 `MAX_RETRIES` 次，退避上限 `RETRY_MAX_DELAY`）。
- **异常隔离**：单个 tick 失败仅记录日志并跳过，不影响整体调度循环。
- **优雅退出**：`--serve` 模式响应 `SIGINT` / `SIGTERM`，分段休眠以便及时停止。
- **断点续跑**：重启后从 `data/xauusd_30m_*.json(l)` 恢复已有 K 线，按 `timestamp` 去重合并。

## 后续可衔接

- 下游 `app/core/predictor.py` 可直接读取 `xauusd_30m_latest_bar.json` 与
  `xauusd_30m_bars.jsonl` 作为 30 分钟预测窗口的输入。
- 如需更长历史，可在 Sina 恢复 K 线接口后切换数据源（见上文），或长期运行本模块自然积累。
