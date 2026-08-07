"""XAU/USD 30 分钟行情获取模块（数据源：新浪财经）。

设计要点
--------
1. **固定 30 分钟预测窗口**（项目核心约束）：所有 K 线 / 接口 / 字段命名均围绕
   ``HORIZON_MINUTES = 30`` / ``PREDICT_WINDOW = "30min"`` 展开，不得调整为其他周期。
2. **数据源 = 新浪财经实时报价** ``hq.sinajs.cn/list=hf_XAU``（伦敦现货黄金 XAU/USD）。
   说明：新浪面向公众的「历史 / 分时 K 线」JSONP 接口（shd2/getkline、forex/kline、
   rshq/kline 等）当前已全部返回 ``Invalid service name`` 已下线；实时报价接口仍可稳定
   访问。因此本模块以「定时拉取实时报价 → 聚合成 30 分钟 OHLC K 线」的方式提供数据，
   既满足「最新 K 线或报价数据」的要求，又完全基于新浪数据源。
3. **数据稳定获取**：HTTP 请求带超时 + 指数退避重试 + 多类异常捕获；任一 tick 失败
   不影响整体循环。
4. **结构化输出**：每条记录包含 ``timestamp / open / high / low / close`` 等字段，
   直接对应项目 ``demo_data`` 的 K 线契约。

可直接通过 ``python -m xauusd_30m_scraper.main --once`` 运行（相对导入，推荐以模块方式执行）。
"""

__version__ = "1.0.0"
__all__ = ["config", "client", "parser", "aggregator", "storage", "scheduler", "models"]
