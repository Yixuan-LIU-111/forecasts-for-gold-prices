"""自定义异常，便于调用方按类型处理。"""


class XAUUSDSError(Exception):
    """基础异常。"""


class FetchError(XAUUSDSError):
    """网络 / HTTP 层获取失败（超时、连接错误、非空校验失败等）。"""


class ParseError(XAUUSDSError):
    """行情串解析失败（格式异常、字段不足、非数值等）。"""


class AggregatorError(XAUUSDSError):
    """聚合 / 落盘异常。"""
