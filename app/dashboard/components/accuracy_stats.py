"""
准确率统计组件
包含：7天/30天滚动准确率、按方向分类准确率、盈亏分布直方图
"""
import streamlit as st
import plotly.graph_objects as go
import plotly.express as px
import pandas as pd

from app.dashboard.api.client import get_accuracy, get_pnl_distribution, get_backtest_results
from app.dashboard.config import config


def render_accuracy_stats():
    """
    渲染准确率统计面板（优化P1: 添加容器边框）
    """
    with st.container(border=True):
        st.markdown(
            "<div class='terminal-header'>准确率统计</div>",
            unsafe_allow_html=True
        )

        accuracy = get_accuracy()

        if accuracy is None:
            st.markdown(
                "<div class='placeholder-card' style='padding:1rem;'>数据不足，请先运行回测</div>",
                unsafe_allow_html=True
            )
            return

        # 关键指标
        col1, col2, col3, col4 = st.columns(4)

        metrics = [
            ("7天准确率", f"{accuracy.get('overall_7d', 0):.1f}%", accuracy.get('overall_7d', 0) >= 60),
            ("30天准确率", f"{accuracy.get('overall_30d', 0):.1f}%", accuracy.get('overall_30d', 0) >= 55),
        ]

        # 获取更多指标
        backtest = get_backtest_results()
        if backtest:
            summary = backtest.get("summary", {})
            metrics.append(("胜率", f"{summary.get('win_rate', 0):.1f}%", summary.get('win_rate', 0) >= 50))
            metrics.append(("盈亏比", f"{summary.get('profit_loss_ratio', 0):.2f}", summary.get('profit_loss_ratio', 0) >= 1.0))

        cols = [col1, col2, col3, col4]
        for col, (label, value, is_good) in zip(cols, metrics):
            with col:
                color = config.COLORS["bullish"] if is_good else config.COLORS["bearish"]
                st.markdown(
                    f"<div class='metric-card'>"
                    f"<div class='metric-label'>{label}</div>"
                    f"<div class='metric-value' style='color:{color};'>{value}</div>"
                    f"</div>",
                    unsafe_allow_html=True
                )

        # 按方向准确率柱状图 + 盈亏分布直方图
        col_left, col_right = st.columns(2)

        with col_left:
            render_direction_accuracy(accuracy)

        with col_right:
            render_pnl_distribution()


def render_direction_accuracy(accuracy: dict):
    """
    渲染按方向分类准确率柱状图
    Args:
        accuracy: 准确率数据
    """
    directions = ["看涨", "看跌", "观望"]
    values = [
        accuracy.get("bullish_accuracy", 0),
        accuracy.get("bearish_accuracy", 0),
        accuracy.get("neutral_accuracy", 0)
    ]
    colors = [config.COLORS["bullish"], config.COLORS["bearish"], config.COLORS["neutral"]]

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=directions,
        y=values,
        marker_color=colors,
        text=[f"{v:.1f}%" for v in values],
        textposition="outside",
        hovertemplate="%{x}<br>准确率: %{y:.1f}%<extra></extra>",
        showlegend=False
    ))

    fig.update_layout(
        title={
            "text": "按方向准确率",
            "font": {"size": 12, "color": "#787b86"},
            "x": 0,
            "xanchor": "left"
        },
        height=200,
        margin=dict(l=10, r=10, t=30, b=10),
        yaxis=dict(title="", range=[0, 100], showgrid=True, gridcolor="#1e222d", color="#787b86"),
        xaxis=dict(title="", color="#787b86"),
        paper_bgcolor="#131722",
        plot_bgcolor="#131722",
        font={"color": "#787b86", "size": 10, "family": "monospace"}
    )

    st.plotly_chart(fig, width='stretch', config={"displayModeBar": False})


def render_pnl_distribution():
    """
    渲染盈亏分布直方图
    """
    pnl_data = get_pnl_distribution()

    if pnl_data is None:
        st.markdown(
            "<div class='placeholder-card' style='padding:1rem;'>暂无盈亏数据</div>",
            unsafe_allow_html=True
        )
        return

    bins = pnl_data.get("bins", [])
    counts = pnl_data.get("counts", [])

    if not bins or not counts:
        return

    # 构建数据
    bin_labels = [f"{bins[i]}-{bins[i+1]}" for i in range(len(bins)-1)]
    colors = [
        config.COLORS["loss"] if (bins[i] + bins[i+1]) / 2 < 0
        else config.COLORS["profit"]
        for i in range(len(bins)-1)
    ]

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=bin_labels,
        y=counts,
        marker_color=colors,
        text=counts,
        textposition="outside",
        hovertemplate="区间: %{x}<br>交易次数: %{y}<extra></extra>",
        showlegend=False
    ))

    fig.update_layout(
        title={
            "text": "盈亏分布",
            "font": {"size": 12, "color": "#787b86"},
            "x": 0,
            "xanchor": "left"
        },
        height=200,
        margin=dict(l=10, r=10, t=30, b=10),
        yaxis=dict(title="", showgrid=True, gridcolor="#1e222d", color="#787b86"),
        xaxis=dict(title="", color="#787b86"),
        paper_bgcolor="#131722",
        plot_bgcolor="#131722",
        font={"color": "#787b86", "size": 10, "family": "monospace"}
    )

    st.plotly_chart(fig, width='stretch', config={"displayModeBar": False})