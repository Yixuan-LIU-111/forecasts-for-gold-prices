# Investing.com 财经日历爬虫

从 [Investing.com 财经日历](https://cn.investing.com/economic-calendar) 提取本周高重要性市场事件，并按类别（就业、通货膨胀、经济活动、央行）过滤，最终持久化为 JSON 与 CSV。

## 功能

- 自动抓取本周（周一至周日）财经日历
- 仅保留“高”重要性事件
- 按关键词匹配筛选指定类别
- 输出字段：日期、时间、货币、活动、重要性、今值、预测值、前值
- 同时保存为 `data/investing_calendar_latest.json` 与 `data/investing_calendar_latest.csv`
- 追加历史记录到 `data/investing_calendar_history.jsonl`

## 安装

```bash
cd investing_calendar_scraper
pip install -r requirements.txt
```

## 使用

```bash
python main.py
```

仅预览不保存：

```bash
python main.py --dry-run
```

开启调试日志：

```bash
python main.py --verbose
```

## 配置

编辑 [config.py](config.py) 可调整：

- `TARGET_IMPORTANCE`：重要性级别（默认 `High`）
- `TARGET_CATEGORIES`：目标类别列表
- `CALENDAR_IFRAME_URL`：日历 widget URL
- 输出文件路径与日志级别

## 关于类别过滤的说明

Investing.com 的服务器端类别筛选接口会被 Cloudflare 拦截，因此本爬虫：

1. 通过公开 widget 抓取完整本周数据；
2. 在本地按重要性过滤；
3. 使用事件名称关键词匹配四类类别。

关键词映射可在 [parser.py](parser.py) 的 `CATEGORY_KEYWORDS` 中调整。

## 常见问题

- **抓取失败/超时**：网络波动或 Cloudflare 策略变化，可稍后重试或检查日志。
- **结果为空**：可能是非交易周或本周无符合条件的事件。
- **类别不准**：Investing.com 未在 widget HTML 中暴露类别字段，关键词分类是近似方案；可在 `parser.py` 中扩展关键词。
