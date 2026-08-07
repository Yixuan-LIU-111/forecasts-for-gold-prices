"""定时拉取调度。

- run_once()：单次拉取 → 解析 → 聚合 → 落盘（供 CLI / 测试复用）。
- Scheduler.run()：按 POLL_INTERVAL_SECONDS 循环拉取，单 tick 失败不影响整体；
  支持 SIGINT/SIGTERM 优雅退出。
"""

import logging
import signal
import time
from typing import Callable, Optional, Tuple

from . import config
from . import storage
from .aggregator import BarAggregator
from .client import fetch_quote_raw
from .errors import XAUUSDSError
from .models import Bar, Quote
from .parser import parse_quote

logger = logging.getLogger(__name__)


def run_once(dry_run: bool = False) -> Tuple[Quote, Bar, BarAggregator]:
    """执行一次完整流水线：拉取 → 解析 → 聚合 → 落盘。

    Returns:
        (quote, current_bar, aggregator)
    """
    raw = fetch_quote_raw()
    quote = parse_quote(raw)

    agg = BarAggregator(storage.load_bars())
    prev = agg.current
    bar = agg.update(quote)

    # 若窗口切换，闭合旧 bar 并落盘
    if prev is not None and prev is not bar and not prev.completed:
        prev.completed = True
        if not dry_run:
            storage.append_completed_bar(prev)

    if not dry_run:
        storage.save_latest_bar(bar)
        storage.save_latest_quote(quote)

    return quote, bar, agg


class Scheduler:
    """周期性拉取调度器（状态在 tick 间保持，便于跨 tick 聚合）。"""

    def __init__(self, poll_interval: Optional[int] = None,
                 on_tick: Optional[Callable[[Quote, Bar], None]] = None):
        self.poll_interval = poll_interval or config.POLL_INTERVAL_SECONDS
        self.on_tick = on_tick
        self._stop = False
        self.aggregator = BarAggregator(storage.load_bars())

    def _handle_tick(self) -> None:
        raw = fetch_quote_raw()
        quote = parse_quote(raw)

        prev = self.aggregator.current
        bar = self.aggregator.update(quote)
        if prev is not None and prev is not bar and not prev.completed:
            prev.completed = True
            storage.append_completed_bar(prev)

        storage.save_latest_bar(bar)
        storage.save_latest_quote(quote)

        logger.info("tick: price=%.2f | bar=%s close=%.2f (n=%d)",
                    quote.last, bar.timestamp, bar.close, bar.count)
        if self.on_tick:
            self.on_tick(quote, bar)

    def run(self) -> None:
        logger.info("启动 XAU/USD 30m 定时拉取（轮询间隔=%ds，周期=%s）",
                    self.poll_interval, config.PREDICT_WINDOW)
        while not self._stop:
            try:
                self._handle_tick()
            except XAUUSDSError as e:
                logger.error("tick 失败（已跳过，继续循环）: %s", e)
            except Exception as e:  # 兜底：任何意外都不应中断调度
                logger.exception("tick 发生意外错误（已跳过）: %r", e)

            # 分段休眠，便于及时响应停止信号
            for _ in range(self.poll_interval):
                if self._stop:
                    break
                time.sleep(1)

        logger.info("调度已停止。")

    def stop(self) -> None:
        self._stop = True


def _make_signal_handler(scheduler: Scheduler):
    def _handler(signum, frame):
        logger.info("收到信号 %s，准备停止…", signum)
        scheduler.stop()
    return _handler


def run_server(poll_interval: Optional[int] = None) -> None:
    """以循环模式运行，并注册信号优雅退出。"""
    sched = Scheduler(poll_interval=poll_interval)
    signal.signal(signal.SIGINT, _make_signal_handler(sched))
    signal.signal(signal.SIGTERM, _make_signal_handler(sched))
    sched.run()
