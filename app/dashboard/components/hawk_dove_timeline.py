"""
鹰鸽指数时间线组件
展示美联储官员近7天讲话的鹰鸽分布柱状图
点击柱子可展开对应的讲话摘要
"""
import streamlit as st
import plotly.graph_objects as go
import pandas as pd

from app.dashboard.api.client import get_hawk_dove_events
from app.dashboard.config import config


def render_hawk_dove_timeline():
    """
    渲染鹰鸽指数时间线（优化P1: 添加容器边框）
    柱状图：X轴=日期，Y轴=鹰鸽分数，绿色=鸽派，红色=鹰派
    """
    with st.container(border=True):
        st.markdown(
            "<div class='terminal-header'>鹰鸽指数时间线 (近7天)</div>",
            unsafe_allow_html=True
        )

        events = get_hawk_dove_events(days=7)

        if not events:
            st.markdown(
                "<div class='placeholder-card' style='padding:1rem;'>暂无鹰鸽事件数据</div>",
                unsafe_allow_html=True
            )
            return

        # 转换为 DataFrame
        df = pd.DataFrame(events)
        df["color"] = df["type"].map({
            "dove": config.COLORS["bullish"],
            "hawk": config.COLORS["bearish"]
        })
        df["date"] = pd.to_datetime(df["date"])

        # 创建柱状图
        fig = go.Figure()

        fig.add_trace(go.Bar(
            x=df["date"],
            y=df["score"],
            marker_color=df["color"],
            text=df["label"],
            textposition="outside",
            hovertemplate=(
                "<b>%{customdata[0]}</b><br>"
                "日期: %{x|%m-%d}<br>"
                "分数: %{y:+.2f}<br>"
                "摘要: %{customdata[1]}<br>"
                "<extra></extra>"
            ),
            customdata=df[["speaker", "summary"]].values,
            showlegend=False,
            width=0.6
        ))

        fig.add_hline(y=0, line_width=1, line_color="#2a2e39", line_dash="dash")

        fig.update_layout(
            height=180,
            margin=dict(l=10, r=10, t=10, b=20),
            xaxis={
                "title": "",
                "showgrid": False,
                "dtick": "D1",
                "tickformat": "%m-%d",
                "color": "#787b86"
            },
            yaxis={
                "title": "",
                "showgrid": True,
                "gridcolor": "#1e222d",
                "zeroline": False,
                "tickformat": ".2f",
                "color": "#787b86"
            },
            paper_bgcolor="#131722",
            plot_bgcolor="#131722",
            font={"color": "#787b86", "size": 9, "family": "monospace"},
            hoverlabel={"bgcolor": "#1c2030", "font_size": 11, "font_color": "#d1d4dc"}
        )

        st.plotly_chart(fig, width='stretch', config={"displayModeBar": False})

        # 在图表下方显示事件摘要列表
        with st.expander("📋 查看讲话详情", expanded=False):
            for _, event in df.iterrows():
                speaker = event.get("speaker", "")
                label = event.get("label", "")
                score = event.get("score", 0)
                summary = event.get("summary", "")
                date_str = pd.to_datetime(event.get("date")).strftime("%m-%d")

                color = config.COLORS["bullish"] if event.get("type") == "dove" else config.COLORS["bearish"]
                icon = "🕊️" if event.get("type") == "dove" else "🦅"

                st.markdown(
                    f"<div style='padding:0.3rem 0; border-bottom:1px solid #1e222d;'>"
                    f"<span style='color:{color}; font-weight:600; font-family:monospace; font-size:0.75rem;'>{icon} {speaker}</span>"
                    f" <span style='color:#4f5564; font-size:0.65rem; font-family:monospace;'>({date_str})</span>"
                    f"<br><span style='font-size:0.75rem; color:#d1d4dc;'>{summary}</span>"
                    f"<br><span style='font-size:0.6rem; color:#787b86; font-family:monospace;'>"
                    f"{label} | 分数: {score:+.2f}</span>"
                    f"</div>",
                    unsafe_allow_html=True
                )