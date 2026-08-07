"""
仪表盘全局配置
管理 API 端点、刷新频率、颜色主题等全局参数
"""
from dataclasses import dataclass, field
from typing import Dict


@dataclass
class DashboardConfig:
    """仪表盘配置"""
    # API 基础地址
    API_BASE_URL: str = "http://localhost:8000/api/v1"

    # 刷新频率（秒）
    REFRESH_SIGNAL: int = 5        # 信号面板（SSE/短轮询）
    REFRESH_PRICE: int = 60        # 行情走势图
    REFRESH_FACTORS: int = 30      # 多因子卡片
    REFRESH_NEWS: int = 30         # 新闻列表
    REFRESH_STATUS: int = 10       # 系统状态

    # 演示模式
    DEMO_MODE: bool = True         # 默认启用演示模式（无后端时可独立运行）

    # 页面标题
    PAGE_TITLE: str = "点时成金 - 黄金价格30分钟方向预测系统"
    PAGE_ICON: str = "📈"

    # 颜色方案 — 终端深色主题；配色规则：涨红跌绿（国内习惯），以 frontend/dashboard.html 现有实现为准，颜色取值不变
    COLORS: Dict[str, str] = field(default_factory=lambda: {
        "bullish": "#ef5350",       # 看涨/利多 — 红（涨红跌绿，与 frontend/dashboard.html 一致）
        "bearish": "#26a69a",       # 看跌/利空 — 绿（涨红跌绿，与 frontend/dashboard.html 一致）
        "neutral": "#787b86",       # 中性/观望 — 暗灰
        "bg_dark": "#0a0e1a",       # 主背景 — 深蓝黑
        "bg_light": "#131722",      # 次背景 — 深灰蓝
        "card_bg": "#1c2030",       # 卡片背景 — 深灰
        "card_border": "#2a2e39",   # 卡片边框 — 暗灰
        "text_primary": "#d1d4dc",  # 主文字色 — 浅灰
        "text_secondary": "#787b86",# 次要文字色 — 中灰
        "text_muted": "#4f5564",    # 弱化文字色 — 暗灰
        "accent_gold": "#f0b90b",   # 金色强调 — 品牌色
        "accent_blue": "#2962ff",   # 蓝色强调 — 交互色
        "gauge_green": "#26a69a",   # 仪表盘绿色区
        "gauge_yellow": "#f0b90b",  # 仪表盘黄色区
        "gauge_red": "#ef5350",     # 仪表盘红色区
        "chart_line": "#2962ff",    # 图表主线色 — 蓝
        "chart_ma": "#f0b90b",      # 移动平均线色 — 金
        "chart_volume": "#2a2e39",  # 成交量柱色 — 暗灰
        "profit": "#ef5350",        # 盈利色（涨红跌绿：盈利=红）
        "loss": "#26a69a",          # 亏损色（涨红跌绿：亏损=绿）
    })


# 全局单例
config = DashboardConfig()