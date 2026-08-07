"""
工具函数
提供格式化、时间处理、颜色映射等通用工具
"""
from datetime import datetime, timedelta
from typing import Optional


def format_time_ago(dt_str: str) -> str:
    """
    将时间字符串转为相对时间描述（如 "3分钟前"）
    Args:
        dt_str: ISO 格式时间字符串
    Returns:
        相对时间描述
    """
    try:
        dt = datetime.fromisoformat(dt_str)
        now = datetime.now()
        diff = now - dt

        if diff < timedelta(seconds=60):
            return "刚刚"
        elif diff < timedelta(minutes=60):
            return f"{int(diff.total_seconds() // 60)}分钟前"
        elif diff < timedelta(hours=24):
            return f"{int(diff.total_seconds() // 3600)}小时前"
        elif diff < timedelta(days=7):
            return f"{diff.days}天前"
        else:
            return dt.strftime("%m-%d %H:%M")
    except (ValueError, TypeError):
        return dt_str


def format_price(price: float, decimals: int = 2) -> str:
    """
    格式化价格数字
    Args:
        price: 价格
        decimals: 小数位数
    Returns:
        格式化后的价格字符串
    """
    if price is None:
        return "--"
    return f"{price:,.{decimals}f}"


def format_pct(value: float, decimals: int = 2) -> str:
    """
    格式化百分比
    Args:
        value: 百分比值（如 0.52 表示 0.52%）
        decimals: 小数位数
    Returns:
        格式化后的百分比字符串
    """
    if value is None:
        return "--"
    sign = "+" if value > 0 else ""
    return f"{sign}{value:.{decimals}f}%"


def format_score(value: float, decimals: int = 2) -> str:
    """
    格式化分数值（带正负号）
    Args:
        value: 分数值
        decimals: 小数位数
    Returns:
        格式化后的分数字符串
    """
    if value is None:
        return "--"
    sign = "+" if value > 0 else ""
    return f"{sign}{value:.{decimals}f}"


def get_trend_arrow(trend: str) -> str:
    """
    获取趋势箭头符号
    Args:
        trend: 趋势方向 (up/down/flat)
    Returns:
        箭头符号
    """
    arrows = {
        "up": "↑",
        "down": "↓",
        "flat": "→"
    }
    return arrows.get(trend, "→")


def get_trend_color_class(trend: str) -> str:
    """
    获取趋势 CSS 类名
    Args:
        trend: 趋势方向 (up/down/flat)
    Returns:
        CSS 类名
    """
    classes = {
        "up": "trend-up",
        "down": "trend-down",
        "flat": "trend-flat"
    }
    return classes.get(trend, "trend-flat")


def get_sentiment_class(sentiment: str) -> str:
    """
    获取情感标签 CSS 类名
    Args:
        sentiment: 情感类型 (bullish/bearish/neutral)
    Returns:
        CSS 类名
    """
    classes = {
        "bullish": "sentiment-bullish",
        "bearish": "sentiment-bearish",
        "neutral": "sentiment-neutral"
    }
    return classes.get(sentiment, "sentiment-neutral")


def get_sentiment_icon(sentiment: str) -> str:
    """
    获取情感标签图标
    Args:
        sentiment: 情感类型
    Returns:
        图标符号
    """
    icons = {
        "bullish": "🔴",        # 涨/看多 = 红（涨红跌绿，与 frontend/dashboard.html 一致）
        "bearish": "🟢",        # 跌/看空 = 绿（涨红跌绿，与 frontend/dashboard.html 一致）
        "neutral": "⚪"
    }
    return icons.get(sentiment, "⚪")


def get_direction_color(direction: str) -> str:
    """
    根据信号方向获取颜色
    Args:
        direction: 信号方向
    Returns:
        十六进制颜色值
    """
    colors = {
        "看涨": "#ef5350",      # 涨 = 红（涨红跌绿，与 frontend/dashboard.html 一致）
        "看跌": "#26a69a",      # 跌 = 绿（涨红跌绿，与 frontend/dashboard.html 一致）
        "观望": "#787b86"
    }
    return colors.get(direction, "#9E9E9E")


def get_position_color(position_pct: int) -> str:
    """
    根据仓位比例获取颜色
    Args:
        position_pct: 仓位比例 (0-100)
    Returns:
        十六进制颜色值
    """
    if position_pct == 0:
        return "#787b86"
    elif position_pct <= 25:
        return "#5c6bc0"
    elif position_pct <= 50:
        return "#42a5f5"
    else:
        return "#2962ff"


def get_strength_label(strength: int) -> str:
    """
    根据信号强度获取文字标签
    Args:
        strength: 信号强度 (0-100)
    Returns:
        强度标签
    """
    if strength >= 60:
        return "强"
    elif strength >= 30:
        return "中"
    else:
        return "弱"


def get_strength_color(strength: int) -> str:
    """
    根据信号强度获取颜色
    Args:
        strength: 信号强度 (0-100)
    Returns:
        十六进制颜色值
    """
    if strength >= 60:
        return "#26a69a"
    elif strength >= 30:
        return "#2962ff"
    else:
        return "#787b86"


def get_confidence_label(confidence_value: float) -> str:
    """
    量化置信度，返回带范围的文字描述
    Args:
        confidence_value: 置信度数值 (0-100)
    Returns:
        带范围的置信度描述
    """
    if confidence_value is None:
        return "—"
    if confidence_value >= 80:
        return f"高 ({confidence_value:.0f}%)"
    elif confidence_value >= 50:
        return f"中 ({confidence_value:.0f}%)"
    else:
        return f"低 ({confidence_value:.0f}%)"


def get_confidence_color(confidence_value: float) -> str:
    """
    根据置信度数值获取颜色
    Args:
        confidence_value: 置信度数值 (0-100)
    Returns:
        十六进制颜色值
    """
    if confidence_value is None:
        return "#787b86"
    if confidence_value >= 80:
        return "#26a69a"
    elif confidence_value >= 50:
        return "#2962ff"
    else:
        return "#787b86"


def get_gauge_color(probability: float) -> str:
    """
    根据概率值获取仪表盘颜色
    Args:
        probability: 概率值 (0-1)
    Returns:
        十六进制颜色值
    """
    if probability >= 0.6:
        return "#ef5350"       # 高上涨概率 = 涨 = 红（涨红跌绿）
    elif probability >= 0.4:
        return "#f0b90b"       # 中性 = 金
    else:
        return "#26a69a"       # 低上涨概率 = 跌 = 绿（涨红跌绿）