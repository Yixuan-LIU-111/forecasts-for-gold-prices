"""30 分钟 K 线聚合器。

将实时报价（last 价格）按固定 30 分钟窗口对齐，聚合为 OHLC bar：
- 窗口起始时间对齐到 30 分钟边界（北京时间）。
- open = 窗口内首笔价格；high/low = 窗口内极值；close = 窗口内最新价格。
- 窗口到达下一个 30 分钟边界时闭合，开始新 bar。
"""

import logging
from datetime import datetime
from typing import List, Optional

from . import config
from .errors import AggregatorError
from .models import Bar, Quote

_FMT = "%Y-%m-%dT%H:%M:%S"


def floor_to_window(dt: datetime) -> datetime:
    """将北京时间（naive）向下对齐到 30 分钟边界。"""
    minute = (dt.minute // config.HORIZON_MINUTES) * config.HORIZON_MINUTES
    return dt.replace(minute=minute, second=0, microsecond=0)


class BarAggregator:
    """维护 30 分钟 K 线序列（已完成 + 当前 forming bar）。"""

    def __init__(self, bars: Optional[List[Bar]] = None):
        self._bars: List[Bar] = list(bars) if bars else []
        # 当前 forming bar = 最后一个且未完成的 bar
        self._current: Optional[Bar] = (
            self._bars[-1] if self._bars and not self._bars[-1].completed else None
        )

    @property
    def current(self) -> Optional[Bar]:
        return self._current

    def update(self, quote: Quote) -> Bar:
        """用一笔实时报价更新聚合序列，返回当前（forming 或新建）bar。"""
        try:
            qdt = datetime.strptime(quote.timestamp, _FMT)
        except Exception as e:  # 时间异常不应中断流程
            logging.getLogger(__name__).warning("时间戳解析失败，使用当前时间: %s", e)
            qdt = datetime.now()

        bar_start = floor_to_window(qdt)
        ts = bar_start.strftime(_FMT)
        price = quote.last

        if self._current is None or self._current.timestamp != ts:
            # 旧 forming bar 在此处随之闭合（由调用方负责落盘）
            new_bar = Bar(
                timestamp=ts,
                open=price,
                high=price,
                low=price,
                close=price,
                count=1,
                completed=False,
            )
            self._bars.append(new_bar)
            self._current = new_bar
            # 内存裁剪
            if len(self._bars) > config.MAX_BARS_IN_MEMORY:
                self._bars = self._bars[-config.MAX_BARS_IN_MEMORY:]
            return new_bar

        # 同一窗口：扩展 high/low，刷新 close
        self._current.high = max(self._current.high, price)
        self._current.low = min(self._current.low, price)
        self._current.close = price
        self._current.count += 1
        return self._current

    def get_bars(self, include_current: bool = True) -> List[Bar]:
        return list(self._bars)

    def latest_bar(self) -> Optional[Bar]:
        return self._current
