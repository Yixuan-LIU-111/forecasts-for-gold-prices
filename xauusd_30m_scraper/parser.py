"""解析新浪 hf_XAU 实时行情串。

行情串示例：
    var hq_str_hf_XAU="4157.78,4077.210,4157.78,4158.13,4179.44,4065.42,17:44:00,4077.21,4077.96,0,0,0,2026-08-05,伦敦现货黄金";

经验证，字段中实时变动的主价格位于索引 0（与索引 2 同步变动）；索引 3/4 为当日
高/低参考；索引 5 为昨收（静态）。新浪现货行情串的 OHLC 字段存在内部不一致
（如偶发 low > high），因此本解析器只负责抽取「最新价 / 时间 / 日期 / 名称」等可靠
字段，30 分钟 K 线的权威 OHLC 由 aggregator 基于最新价采样生成。
"""

import logging
import re
from datetime import datetime, timezone

from . import config
from .errors import ParseError
from .models import Quote

_QUOTE_RE = re.compile(r'var\s+hq_str_(?P<symbol>\w+)="(?P<body>[^"]*)"', re.S)

# 行情串数值字段索引（基于实证双样本对照）
_IDX_LAST = 0        # 最新价（实时变动的主价格）
_IDX_ASK = 1         # 卖价（参考，可能异常）
_IDX_OPEN_FEED = 2   # 行情串提供的开（参考）
_IDX_HI_LO_A = 3     # 当日高/低之一
_IDX_HI_LO_B = 4     # 当日高/低之一
_IDX_PREV_CLOSE = 5  # 昨收（静态）
_IDX_TIME = 6        # HH:MM:SS
_IDX_DATE = 12       # YYYY-MM-DD
_IDX_NAME = 13       # 中文名称


def parse_quote(raw_text: str) -> Quote:
    """将原始行情串解析为结构化 Quote。

    Raises:
        ParseError: 格式异常、字段不足或数值解析失败。
    """
    if not raw_text:
        raise ParseError("原始文本为空")

    m = _QUOTE_RE.search(raw_text)
    if not m:
        raise ParseError("未匹配到 hq_str 行情串（接口可能返回空或限流）")

    symbol = m.group("symbol")
    body = m.group("body").strip()
    if not body:
        raise ParseError("行情串内容为空（可能为接口限流或未带 Referer）")

    parts = [p.strip() for p in body.split(",")]
    if len(parts) < 6:
        raise ParseError(f"字段数量不足（期望>=6，实际{len(parts)}）: {parts}")

    try:
        nums = [float(p) for p in parts[:6]]
    except ValueError as e:
        raise ParseError(f"数值字段解析失败 {parts[:6]}: {e}")

    last = nums[_IDX_LAST]
    ask = nums[_IDX_ASK]
    open_feed = nums[_IDX_OPEN_FEED]
    high = max(nums[_IDX_HI_LO_A], nums[_IDX_HI_LO_B])   # 取较大者为当日高
    low = min(nums[_IDX_HI_LO_A], nums[_IDX_HI_LO_B])    # 取较小者为当日低
    prev_close = nums[_IDX_PREV_CLOSE]

    time_str = parts[_IDX_TIME] if len(parts) > _IDX_TIME else ""
    date_str = parts[_IDX_DATE] if len(parts) > _IDX_DATE else ""
    name = parts[_IDX_NAME] if len(parts) > _IDX_NAME else config.SERIES_NAME_ZH

    if date_str and time_str:
        timestamp = f"{date_str}T{time_str}"
    else:
        # 兜底：用当前本地时间（北京时间近似）
        timestamp = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        logging.getLogger(__name__).warning("行情串缺时间/日期，已用本地时间兜底: %s", timestamp)

    return Quote(
        symbol=symbol,
        series_name=name or config.SERIES_NAME_ZH,
        timestamp=timestamp,
        last=last,
        bid=None,            # 新浪现货行情串未给出可靠买价，置空
        ask=ask,
        open=open_feed,
        high=high,
        low=low,
        prev_close=prev_close,
        raw=nums,
        fetched_at=datetime.now(timezone.utc).isoformat(),
    )
