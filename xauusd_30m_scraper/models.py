"""数据模型：实时报价与 30 分钟 K 线 bar。

采用标准库 dataclass，零第三方依赖，便于被 app 直接 import。
"""

from dataclasses import dataclass, field, asdict
from typing import Optional


@dataclass
class Quote:
    """XAU/USD 实时报价（来自新浪 hq.sinajs.cn）。

    字段说明：
    - timestamp：报价对应的北京时间（YYYY-MM-DDTHH:MM:SS）。
    - last：最新价（取自行情串中实时变动的主价格字段）。
    - bid / ask：买卖价（来自行情串，部分品种可能为空或异常，仅作参考）。
    - open/high/low/prev_close：行情串中提供的当日开/高/低/昨收（仅供参考，
      因新浪现货行情串的 OHLC 字段存在内部不一致，30 分钟 K 线的权威 OHLC
      由聚合器基于 last 采样生成，不依赖此处）。
    - raw：原始行情串拆分后的数值列表，便于排查。
    """

    symbol: str
    series_name: str
    timestamp: str                 # 北京时间 ISO，如 2026-08-05T17:44:00
    last: float
    bid: Optional[float] = None
    ask: Optional[float] = None
    open: Optional[float] = None
    high: Optional[float] = None
    low: Optional[float] = None
    prev_close: Optional[float] = None
    raw: list = field(default_factory=list)
    fetched_at: str = ""           # 本地拉取时间（ISO，含时区）

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Bar:
    """30 分钟 K 线（OHLC），由实时报价聚合成。

    - timestamp：该 30 分钟窗口的起始时间（北京时间，对齐到 30 分钟边界）。
    - open/high/low/close：窗口内的首价 / 最高 / 最低 / 最新价。
    - count：窗口内采样点数。
    - window：固定 "30min"。
    """

    timestamp: str                 # 窗口起始时间（北京时间 ISO）
    open: float
    high: float
    low: float
    close: float
    count: int = 1
    window: str = "30min"
    symbol: str = "hf_XAU"
    completed: bool = False        # 窗口是否已闭合（到达下一个 30 分钟边界）

    def to_dict(self) -> dict:
        return asdict(self)
