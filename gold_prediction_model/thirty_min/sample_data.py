"""合成 30 分钟数据生成器 —— 用于示例入口的可运行演示。

真实 30 分钟历史目前几乎为空（xauusd_30m_scraper 刚启动），为让
训练 / 评估 / 消融 / 推理链路**现在就能端到端跑通**，提供一份可复现的
合成 30 分钟 XAU/USD 数据：

- 价格：近 24h 交易的几何布朗运动 + 日内季节性（亚盘/欧盘/美盘波动差异）。
- 新闻情感：泊松过程随机生成事件；关键——**注入「情感→下一窗口收益」的
  弱信号**，使情感特征在消融中能产生可观测的（小幅度）增量，
  从而真实演示方案 §3.5 的核心假设验证流程。
- 严格前视安全：新闻事件时间戳早于其影响的目标收益。

仅用于开发 / 演示；生产以真实数据（xauusd_30m_scraper 输出）为准。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from . import config
from .logging_setup import get_logger

logger = get_logger("thirty_min.sample")


def generate_synthetic(n_bars: int = 2000, seed: int = 42,
                       start: str = "2026-07-01 09:00:00"):
    """生成 (price_df, news_df) 合成数据对。

    关键设计（用于诚实演示核心假设）：
    - 引入一个潜在的「情感状态」序列 s_t（AR(1) 平滑过程）。
    - 新闻情感分值由 s_t 加噪生成（保证新闻与潜在情感一致）。
    - **未来 1 根 30 分钟收益率** = 基础随机游走 + beta·s_{t-1}（因果、前视安全）：
      当前情感状态越高，下一窗口越偏涨。
    - 因此「情感聚合特征(sent_mean 等)」对下一窗口方向具有**可检测的预测力**，
      而纯技术特征不含该信息。消融对比中「含情感」应显著优于「不含情感」。

    该信号为构造已知信号，仅用于端到端演示与假设验证；生产以真实数据为准。
    """
    rng = np.random.default_rng(seed)
    bar_min = config.BAR_MINUTES
    start_ts = pd.Timestamp(start)
    idx = pd.date_range(start=start_ts, periods=n_bars, freq=f"{bar_min}min")

    # ---- 潜在情感状态 AR(1) ----
    phi = 0.90
    s = np.zeros(n_bars)
    for t in range(1, n_bars):
        s[t] = phi * s[t - 1] + rng.normal(0, 0.35)
    s = np.clip(s, -1.0, 1.0)

    # ---- 价格 GBM + 日内季节性 + 情感因果漂移 ----
    dt = bar_min / (60 * 24 * 252)
    drift = 0.0                         # 无趋势：技术特征无动量可榨取，凸显情感增量
    vol = 0.12
    hour = idx.hour + idx.minute / 60.0
    intraday = 0.6 + 0.8 * np.exp(-((hour - 14) ** 2) / 8)
    base_ret = rng.normal(drift * dt, vol * np.sqrt(dt) * intraday, n_bars)

    beta = 0.0022                       # 情感→下一窗口收益强度（可检测但非完美）
    signal = np.zeros(n_bars)
    signal[1:] = beta * s[:-1]          # t 处收益受 t-1 情感状态影响（因果）
    log_ret = base_ret + signal
    close = 2300.0 * np.exp(np.cumsum(log_ret))
    close = np.maximum(close, 1.0)

    # ---- 新闻事件：分值 = 潜在情感 + 噪声（与潜在情感一致）----
    n_news = max(40, n_bars // 8)
    news_pos = np.sort(rng.integers(0, n_bars, size=n_news))
    scores = np.clip(s[news_pos] + rng.normal(0, 0.12, len(news_pos)), -1.0, 1.0)
    conf = rng.uniform(0.5, 0.95, len(news_pos))

    # ---- 构造 OHLC ----
    open_ = np.empty(n_bars)
    open_[0] = close[0] * (1 - log_ret[0])
    open_[1:] = close[:-1]
    noise_h = np.abs(rng.normal(0, 0.0006, n_bars))
    noise_l = np.abs(rng.normal(0, 0.0006, n_bars))
    high = np.maximum(open_, close) * (1 + noise_h)
    low = np.minimum(open_, close) * (1 - noise_l)

    price_df = pd.DataFrame({
        "open": open_, "high": high, "low": low, "close": close,
        "volume": rng.integers(500, 5000, n_bars).astype(float),
        "sampling_count": rng.integers(20, 60, n_bars).astype(int),
    }, index=idx)
    price_df.index.name = "bar_start"

    # ---- 新闻 df ----
    label = np.where(scores > 0.15, "positive", np.where(scores < -0.15, "negative", "neutral"))
    sources = rng.choice(["Fed", "WhiteHouse", "AP", "CNN"], size=len(news_pos))
    news_df = pd.DataFrame({
        "ts": idx[news_pos].tz_localize(None),
        "sentiment_score": scores,
        "confidence": conf,
        "label": label,
        "source": sources,
    })
    logger.info("合成数据：%d 根 30 分钟 bar，%d 条新闻事件（已注入可检测的情感→收益信号，beta=%.4f）",
                n_bars, len(news_df), beta)
    return price_df, news_df
