"""
信号面板组件
包含：方向信号卡片、上涨概率仪表盘、信号强度进度条、建议仓位、多空评分条
以及因子贡献度归因条形图
"""
import streamlit as st
import plotly.graph_objects as go
import plotly.express as px
import pandas as pd

from app.dashboard.api.client import get_latest_signal, get_signal_attribution
from app.dashboard.utils.css import signal_card_html
from app.dashboard.utils.helpers import (
    get_strength_color, get_strength_label, get_position_color,
    get_gauge_color, get_direction_color,
    get_confidence_label, get_confidence_color
)
from app.dashboard.config import config


def render_signal_panel():
    """
    渲染信号面板（核心决策区）（优化P1: 添加容器边框）
    包含5列信号卡片 + 因子贡献度归因图
    """
    signal = get_latest_signal()

    if signal is None:
        st.markdown(
            "<div class='placeholder-card'>等待首次信号生成中...</div>",
            unsafe_allow_html=True
        )
        return

    # 使用边框容器
    with st.container(border=True):
        # === 5列信号卡片 ===
        c1, c2, c3, c4, c5 = st.columns(5)

        with c1:
            # 方向信号卡片
            direction = signal.get("direction", "观望")
            direction_en = signal.get("direction_en", "neutral")
            confidence = signal.get("confidence", "中")
            html = signal_card_html(direction, direction_en, confidence)
            st.markdown(html, unsafe_allow_html=True)

        with c2:
            # 上涨概率 - 使用 Plotly Gauge Chart
            probability = signal.get("probability", 0.5)
            gauge_color = get_gauge_color(probability)
            fig = go.Figure(go.Indicator(
            mode="gauge+number+delta",
            value=probability * 100,
            number={"suffix": "%", "font": {"size": 24, "color": gauge_color, "family": "monospace"}},
            title={"text": "上涨概率", "font": {"size": 11, "color": "#787b86"}},
            delta={"reference": 50, "valueformat": ".1f"},
            gauge={
                "axis": {"range": [0, 100], "tickwidth": 1, "tickcolor": "#2a2e39", "tickfont": {"color": "#4f5564", "size": 8}},
                "bar": {"color": gauge_color, "thickness": 0.25},
                "bgcolor": "#0a0e1a",
                "borderwidth": 1,
                "bordercolor": "#2a2e39",
                "steps": [
                    {"range": [0, 40], "color": "rgba(38,166,154,0.1)"},   # 低上涨概率 = 跌 = 绿
                    {"range": [40, 60], "color": "rgba(240,185,11,0.1)"},  # 中性
                    {"range": [60, 100], "color": "rgba(239,83,80,0.1)"}   # 高上涨概率 = 涨 = 红
                ],
                "threshold": {
                    "line": {"color": gauge_color, "width": 3},
                    "thickness": 0.75,
                    "value": probability * 100
                }
            }
        ))
        fig.update_layout(
            height=140,
            margin=dict(l=10, r=10, t=30, b=10),
            paper_bgcolor="#131722",
            plot_bgcolor="#131722",
            font={"color": "#d1d4dc", "family": "monospace", "size": 10}
        )
        st.plotly_chart(fig, width='stretch', config={"displayModeBar": False})

        with c3:
            # 信号强度进度条
            strength = signal.get("strength", 50)
            strength_label = get_strength_label(strength)
            strength_color = get_strength_color(strength)

            st.markdown(
                f"""
                <div class="signal-card">
                    <div class="label">信号强度</div>
                    <div class="value" style="color:{strength_color};">
                        {strength}<span style="font-size:0.7rem; color:#4f5564;">/100</span>
                    </div>
                    <div style="background:#0a0e1a; border-radius:3px; height:6px; margin:0.4rem 0;">
                        <div style="background:{strength_color}; width:{strength}%; height:6px; border-radius:3px; transition:width 0.5s;"></div>
                    </div>
                    <div class="sub-text" style="color:{strength_color};">
                        [{strength_label}]
                    </div>
                </div>
                """,
                unsafe_allow_html=True
            )

        with c4:
            # 建议仓位
            position = signal.get("position", "观望")
            position_pct = signal.get("position_pct", 0)
            pos_color = get_position_color(position_pct)

            st.markdown(
                f"""
                <div class="signal-card">
                    <div class="label">建议仓位</div>
                    <div class="value" style="color:{pos_color};">
                        {position}
                    </div>
                    <div class="sub-text">
                        {f'{position_pct}%' if position_pct > 0 else '空仓'}
                    </div>
                    <div style="margin-top:0.3rem; font-family:monospace; font-size:0.6rem; color:#4f5564;">
                        SL: {signal.get('stop_loss', '--')} | TP: {signal.get('take_profit', '--')}
                    </div>
                </div>
                """,
                unsafe_allow_html=True
            )

        with c5:
            # 多空评分条
            score = signal.get("bull_bear_score", 50)
            score_color = get_gauge_color(score / 100)
            score_label = "偏多" if score > 55 else ("偏空" if score < 45 else "中性")

            st.markdown(
                f"""
                <div class="signal-card">
                    <div class="label">多空评分</div>
                    <div class="value" style="color:{score_color};">
                        {score}<span style="font-size:0.7rem; color:#4f5564;">/100</span>
                    </div>
                    <div class="sub-text" style="color:{score_color};">{score_label}</div>
                    <div style="margin-top:0.4rem; position:relative; height:16px;">
                        <div style="
                            position:absolute; left:0; right:0; top:6px; height:3px;
                            background:linear-gradient(to right, #ef5350, #787b86, #26a69a);
                            border-radius:2px;
                        "></div>
                        <div style="
                            position:absolute; left:{score}%; top:0px;
                            width:14px; height:14px; border-radius:50%;
                            background:{score_color}; border:2px solid #0a0e1a;
                            transform:translateX(-50%);
                        "></div>
                    </div>
                    <div style="display:flex; justify-content:space-between; font-size:0.55rem; color:#4f5564; margin-top:0.15rem; font-family:monospace;">
                        <span>空头</span>
                        <span>多头</span>
                    </div>
                </div>
                """,
                unsafe_allow_html=True
            )

        # === 因子贡献度归因条形图 ===
        attribution = get_signal_attribution()
        if attribution:
            st.markdown("<div style='margin-top:0.5rem;'></div>", unsafe_allow_html=True)
            render_attribution_chart(signal, attribution)


def render_attribution_chart(signal: dict, attribution: list):
    """
    渲染因子贡献度归因条形图
    Args:
        signal: 当前信号数据
        attribution: 因子归因列表
    """
    direction = signal.get("direction", "观望")
    probability = signal.get("probability", 0.5)

    # 准备数据
    df = pd.DataFrame(attribution)
    df["value_abs"] = df["value"].abs()
    df["color"] = df["color"].map({"green": config.COLORS["bullish"], "red": config.COLORS["bearish"]})
    # 按绝对值排序
    df = df.sort_values("value_abs", ascending=True)

    # 创建水平条形图
    fig = go.Figure()
    fig.add_trace(go.Bar(
        y=df["factor"],
        x=df["value"],
        orientation="h",
        marker_color=df["color"],
        text=df["value"].apply(lambda x: f"{x:+.2f}"),
        textposition="outside",
        hovertemplate="<b>%{y}</b><br>贡献度: %{x:+.2f}<br>%{customdata}<extra></extra>",
        customdata=df["detail"],
        showlegend=False
    ))

    # 添加垂直线（零轴）
    fig.add_vline(x=0, line_width=1, line_color="#2a2e39")

    fig.update_layout(
        title={
            "text": f"信号归因: {direction} (概率 {probability*100:.0f}%)",
            "font": {"size": 12, "color": "#787b86"},
            "x": 0,
            "xanchor": "left"
        },
        xaxis={
            "title": "",
            "zeroline": False,
            "showgrid": True,
            "gridcolor": "#1e222d",
            "tickformat": ".2f",
            "color": "#787b86"
        },
        yaxis={
            "title": "",
            "autorange": "reversed",
            "color": "#787b86"
        },
        height=200,
        margin=dict(l=10, r=40, t=40, b=10),
        paper_bgcolor="#131722",
        plot_bgcolor="#131722",
        font={"color": "#787b86", "size": 10, "family": "monospace"}
    )

    # 图表下方显示模型信息
    col1, col2 = st.columns([3, 1])
    with col1:
        st.plotly_chart(fig, width='stretch', config={"displayModeBar": False})
    with col2:
        model = signal.get("model", "—")
        confidence_value = signal.get("confidence_value", None)
        confidence_label = get_confidence_label(confidence_value)
        confidence_color = get_confidence_color(confidence_value)
        st.markdown(
            f"""
            <div style="padding:0.6rem; background:#1c2030; border-radius:4px; height:100%; border:1px solid #2a2e39;">
                <div style="font-size:0.6rem; color:#4f5564; text-transform:uppercase; letter-spacing:0.5px;">模型</div>
                <div style="font-size:0.75rem; font-weight:600; color:#d1d4dc; font-family:monospace;">{model}</div>
                <div style="font-size:0.6rem; color:#4f5564; text-transform:uppercase; letter-spacing:0.5px; margin-top:0.4rem;">置信度（量化）</div>
                <div style="font-size:0.8rem; font-weight:600; color:{confidence_color}; font-family:monospace;">{confidence_label}</div>
                <div style="font-size:0.55rem; color:#4f5564; margin-top:0.2rem; font-family:monospace;">
                    参考: 高(≥80%) | 中(50-79%) | 低(&lt;50%)
                </div>
            </div>
            """,
            unsafe_allow_html=True
        )