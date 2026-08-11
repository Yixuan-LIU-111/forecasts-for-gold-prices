"""
「点时成金」黄金价格预测系统仪表盘
Streamlit 主入口文件

基于 前端页面设计V2.md 实现 + 优化P1 调整
  - 优化1: 避免英文表述（专业术语除外）
  - 优化2: 卡片大小位置一致
  - 优化3: 置信度量化（给出具体数值和参考范围）
  - 优化4: 相关数据用边框框在一起
  - 优化5: 补充仪表盘说明
  - 优化6: 时间筛选器对齐内容
  - 优化7: 左侧导航栏 + 多页签

启动方式: streamlit run app/dashboard/app.py
"""
import os
import sys

# 将项目根目录加入 sys.path（兼容开发与 PyInstaller 打包环境）
from app.frozen import PROJECT_ROOT
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import streamlit as st
from streamlit_autorefresh import st_autorefresh

from app.dashboard.config import config
from app.dashboard.utils.css import inject_css
from app.dashboard.components.status_bar import render_status_bar
from app.dashboard.components.signal_panel import render_signal_panel
from app.dashboard.components.price_chart import render_price_chart
from app.dashboard.components.factor_cards import render_factor_cards
from app.dashboard.components.hawk_dove_timeline import render_hawk_dove_timeline
from app.dashboard.components.backtest_panel import render_backtest_panel
from app.dashboard.components.accuracy_stats import render_accuracy_stats
from app.dashboard.components.news_list import render_news_list
from app.dashboard.components.system_status import render_system_status


# ============================================================
# 页面定义
# ============================================================
PAGES = {
    "仪表盘概览": "overview",
    "实时行情": "market",
    "回测分析": "backtest",
    "新闻动态": "news",
}

PAGE_ICONS = {
    "仪表盘概览": "🏠",
    "实时行情": "📊",
    "回测分析": "📈",
    "新闻动态": "📰",
}


def render_sidebar():
    """渲染侧边栏导航（终端风格）"""
    with st.sidebar:
        # 系统 Logo 和标题
        st.markdown(
            """
            <div class="nav-logo">
                <div class="logo-icon">Au</div>
                <div class="logo-title">点时成金</div>
                <div class="logo-subtitle">GOLD PREDICTION TERMINAL</div>
            </div>
            """,
            unsafe_allow_html=True
        )

        # 导航菜单
        selected = st.radio(
            "导航",
            list(PAGES.keys()),
            format_func=lambda x: f"{PAGE_ICONS.get(x, '')} {x}",
            label_visibility="collapsed",
            key="nav_radio"
        )

        # 侧边栏底部信息
        st.sidebar.markdown(
            f"""
            <div class="nav-footer">
                REFRESH: 60s<br>
                MODE: {"DEMO" if config.DEMO_MODE else "LIVE"}
            </div>
            """,
            unsafe_allow_html=True
        )

    return PAGES[selected]


def render_dashboard_description():
    """渲染仪表盘说明（优化P1-5）"""
    st.markdown(
        """
        <div class="dashboard-desc">
            <strong>「点时成金」</strong> 是一个基于多因子模型的黄金价格30分钟方向预测系统。
            系统综合 <strong>美元指数(DXY)</strong>、<strong>通胀保值债券收益率(TIPS)</strong>、
            <strong>波动率指数(VIX)</strong>、<strong>地缘政治风险(GPR)</strong>、
            <strong>新闻情感分析</strong> 和 <strong>美联储鹰鸽指数</strong> 六大因子，
            通过机器学习模型（LightGBM + XGBoost 加权集成）生成未来30分钟涨跌方向预测。
        </div>
        """,
        unsafe_allow_html=True
    )


# ============================================================
# 各页面渲染函数
# ============================================================

def page_overview():
    """仪表盘概览页面"""
    # 顶部状态栏
    render_status_bar()

    # 仪表盘说明
    render_dashboard_description()

    # 核心信号面板（含因子归因图）
    render_signal_panel()


def page_market():
    """实时行情页面"""
    # 时间筛选器（优化P1-6: 对齐内容）
    st.markdown(
        """
        <div class="time-filter-row">
            <span class="filter-label">行情时间范围:</span>
        </div>
        """,
        unsafe_allow_html=True
    )
    time_range = st.selectbox(
        "时间范围",
        options=["1小时", "4小时", "1天", "3天", "7天"],
        index=1,
        label_visibility="collapsed",
        key="time_range_market"
    )

    # 行情与因子（双栏布局）
    col1, col2 = st.columns([2, 1])

    with col1:
        # XAU/USD 价格走势图（含 MA20 + 成交量）
        range_map = {"1小时": "1h", "4小时": "4h", "1天": "1d", "3天": "3d", "7天": "7d"}
        render_price_chart(range_hours=range_map.get(time_range, "4h"))

    with col2:
        # 多因子实时卡片
        render_factor_cards()

        # 鹰鸽指数时间线
        render_hawk_dove_timeline()


def page_backtest():
    """回测分析页面"""
    col_left, col_right = st.columns(2)

    with col_left:
        # 回测参数配置 + 收益曲线 + 逐笔交易明细
        render_backtest_panel()

    with col_right:
        # 准确率统计 + 盈亏分布
        render_accuracy_stats()


def page_news():
    """新闻动态页面"""
    render_news_list()


# ============================================================
# 主入口
# ============================================================

def main():
    """仪表盘主入口"""
    # 页面配置
    st.set_page_config(
        page_title=config.PAGE_TITLE,
        page_icon=config.PAGE_ICON,
        layout="wide",
        initial_sidebar_state="expanded"
    )

    # 注入自定义 CSS
    inject_css()

    # 自动刷新（行情图 60s 刷新）
    st_autorefresh(interval=config.REFRESH_PRICE * 1000, key="auto_refresh")

    # 渲染侧边栏导航
    current_page = render_sidebar()

    # 主标题（终端风格 — 紧凑、金色品牌色）
    st.markdown(
        f"<div style='font-size:1.1rem; font-weight:700; color:#f0b90b; "
        f"letter-spacing:1px; margin-bottom:0.3rem; font-family:monospace;'>"
        f"Au · {config.PAGE_TITLE}</div>",
        unsafe_allow_html=True
    )

    # 根据当前页面渲染内容
    if current_page == "overview":
        page_overview()
    elif current_page == "market":
        page_market()
    elif current_page == "backtest":
        page_backtest()
    elif current_page == "news":
        page_news()

    # 底部系统状态（所有页面均显示，折叠状态）
    with st.expander("系统状态与设置", expanded=False):
        render_system_status()


if __name__ == "__main__":
    main()