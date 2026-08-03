"""
多因子实时指标卡片组件
展示 DXY、TIPS、VIX、GPR、情感分数、鹰鸽指数等 6 个因子
每个卡片包含：当前值、趋势箭头、变化百分比、数据来源
"""
import streamlit as st

from app.dashboard.api.client import get_factors
from app.dashboard.utils.helpers import (
    get_trend_arrow, get_trend_color_class, format_price, format_pct, format_score
)


def render_factor_cards():
    """
    渲染多因子实时指标卡片（优化P1: 添加边框容器）
    使用 3 列 x 2 行排列
    """
    factors_data = get_factors()

    if factors_data is None:
        st.markdown(
            "<div class='placeholder-card'>等待因子数据采集...</div>",
            unsafe_allow_html=True
        )
        return

    factors = factors_data.get("factors", [])

    if not factors:
        st.markdown(
            "<div class='placeholder-card'>暂无因子数据</div>",
            unsafe_allow_html=True
        )
        return

    # 使用边框容器分组
    with st.container(border=True):
        st.markdown(
            "<div class='terminal-header'>多因子实时指标</div>",
            unsafe_allow_html=True
        )

        # 3 列 x 2 行排列
        for i in range(0, len(factors), 3):
            row_factors = factors[i:i + 3]
            cols = st.columns(3)

            for col, factor in zip(cols, row_factors):
                with col:
                    render_single_factor(factor)


def render_single_factor(factor: dict):
    """
    渲染单个因子卡片
    Args:
        factor: 因子数据字典
    """
    name = factor.get("name", "")
    label = factor.get("label", name)
    value = factor.get("value", 0)
    change = factor.get("change", 0)
    change_pct = factor.get("change_pct", None)
    trend = factor.get("trend", "flat")
    unit = factor.get("unit", "")
    source = factor.get("source", "")

    # 趋势箭头和颜色
    arrow = get_trend_arrow(trend)
    trend_class = get_trend_color_class(trend)

    # 格式化值
    if name == "DXY":
        value_str = format_price(value, 3)
        change_str = format_price(change, 3)
    elif name == "TIPS":
        value_str = f"{value:.2f}{unit}"
        change_str = format_pct(change, 2)
    elif name == "sentiment":
        value_str = format_score(value, 2)
        change_str = format_score(change, 2)
    elif name == "hawk_dove":
        value_str = format_score(value, 2)
        change_str = ""
    else:
        value_str = format_price(value, 2)
        change_str = format_pct(change_pct, 1) if change_pct is not None else format_price(change, 2)

    # 趋势颜色
    trend_color = factor.get("trend_color", "gray")
    color_map = {"red": "#ef5350", "green": "#26a69a", "gray": "#787b86"}
    arrow_color = color_map.get(trend_color, "#787b86")

    # 构建卡片 HTML
    html = f"""
    <div class="factor-card">
        <div class="factor-name">{label}</div>
        <div class="factor-value">{value_str}</div>
        <div class="factor-change" style="color:{arrow_color};">
            <span class="{trend_class}">{arrow}</span>
            {change_str}
        </div>
        <div class="factor-source">{source}</div>
    </div>
    """

    st.markdown(html, unsafe_allow_html=True)