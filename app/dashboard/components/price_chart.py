"""
行情走势图组件
XAU/USD 价格走势图，叠加 MA20 移动平均线，支持时间范围切换
"""
import streamlit as st
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd

from app.dashboard.api.client import get_market_data
from app.dashboard.utils.helpers import format_price, format_pct
from app.dashboard.config import config


def render_price_chart(range_hours: str = "4h"):
    """
    渲染 XAU/USD 价格走势图（优化P1: 时间范围由外部传入）
    包含：主价格线 + MA20 + 成交量 + 价格摘要
    Args:
        range_hours: 时间范围 ("1h", "4h", "1d", "3d", "7d")
    """
    # 获取行情数据
    market_data = get_market_data()

    if market_data is None:
        st.markdown(
            "<div class='placeholder-card'>暂无行情数据</div>",
            unsafe_allow_html=True
        )
        return

    prices = market_data.get("prices", [])
    if not prices:
        st.markdown(
            "<div class='placeholder-card'>暂无价格数据</div>",
            unsafe_allow_html=True
        )
        return

    # 使用边框容器
    with st.container(border=True):
        # 转换为 DataFrame
        df = pd.DataFrame(prices)
        df["time"] = pd.to_datetime(df["time"])

        # 根据时间范围过滤数据
        now = df["time"].max()
        range_map = {"1h": pd.Timedelta(hours=1), "4h": pd.Timedelta(hours=4),
                     "1d": pd.Timedelta(days=1), "3d": pd.Timedelta(days=3), "7d": pd.Timedelta(weeks=1)}
        start_time = now - range_map.get(range_hours, pd.Timedelta(hours=4))
        df_filtered = df[df["time"] >= start_time].copy()

        if len(df_filtered) < 2:
            df_filtered = df.copy()

        # 计算 MA20
        df_filtered["MA20"] = df_filtered["price"].rolling(window=min(20, len(df_filtered))).mean()

        # 创建子图：主图 + 成交量
        fig = make_subplots(
            rows=2, cols=1,
            shared_xaxes=True,
            vertical_spacing=0.05,
            row_heights=[0.75, 0.25],
            subplot_titles=("XAU/USD 实时价格", "成交量")
        )

        # 主价格线
        fig.add_trace(
            go.Scatter(
                x=df_filtered["time"],
                y=df_filtered["price"],
                mode="lines",
                name="XAU/USD",
                line=dict(color=config.COLORS["chart_line"], width=2),
                hovertemplate="%{x|%H:%M}<br>价格: $%{y:.2f}<extra></extra>"
            ),
            row=1, col=1
        )

        # MA20 移动平均线
        if df_filtered["MA20"].notna().any():
            fig.add_trace(
                go.Scatter(
                    x=df_filtered["time"],
                    y=df_filtered["MA20"],
                    mode="lines",
                    name="MA20",
                    line=dict(color=config.COLORS["chart_ma"], width=1.5, dash="dash"),
                    hovertemplate="%{x|%H:%M}<br>MA20: $%{y:.2f}<extra></extra>"
                ),
                row=1, col=1
            )

        # 成交量柱状图
        volume_color = [config.COLORS["chart_volume"]] * len(df_filtered)
        fig.add_trace(
            go.Bar(
                x=df_filtered["time"],
                y=df_filtered["volume"],
                name="成交量",
                marker_color=volume_color,
                hovertemplate="%{x|%H:%M}<br>成交量: %{y}<extra></extra>"
            ),
            row=2, col=1
        )

        # 更新布局
        current_price = market_data.get("current_price", 0)
        change = market_data.get("change", 0)
        change_pct = market_data.get("change_pct", 0)
        high = market_data.get("high_24h", 0)
        low = market_data.get("low_24h", 0)
        change_color = config.COLORS["bullish"] if change >= 0 else config.COLORS["bearish"]
        change_sign = "+" if change >= 0 else ""

        fig.update_layout(
            title={
                "text": (
                    f"<b style='color:#d1d4dc;'>XAU/USD</b>  "
                    f"<span style='font-size:1.1rem; color:#f0b90b; font-family:monospace;'><b>${format_price(current_price)}</b></span>  "
                    f"<span style='color:{change_color}; font-size:0.8rem; font-family:monospace;'>"
                    f"{change_sign}{format_price(change)} ({change_sign}{format_pct(change_pct, 2)})</span>"
                ),
                "font": {"size": 13},
                "x": 0,
                "xanchor": "left"
            },
            height=420,
            margin=dict(l=10, r=20, t=50, b=10),
            hovermode="x unified",
            legend=dict(
                orientation="h",
                yanchor="bottom",
                y=1.02,
                xanchor="right",
                x=1,
                font={"color": "#787b86", "size": 10}
            ),
            paper_bgcolor="#131722",
            plot_bgcolor="#131722",
            font={"color": "#787b86", "size": 10, "family": "monospace"}
        )

        fig.update_xaxes(
            title="",
            showgrid=True,
            gridcolor="#1e222d",
            row=2, col=1,
            color="#787b86"
        )
        fig.update_xaxes(
            showgrid=True,
            gridcolor="#1e222d",
            row=1, col=1,
            color="#787b86"
        )
        fig.update_yaxes(
            title="",
            showgrid=True,
            gridcolor="#1e222d",
            row=1, col=1,
            color="#787b86"
        )
        fig.update_yaxes(
            title="",
            showgrid=True,
            gridcolor="#1e222d",
            row=2, col=1,
            color="#787b86"
        )

        st.plotly_chart(fig, width='stretch', config={"displayModeBar": True})

        # 价格摘要信息
        col1, col2, col3, col4 = st.columns(4)
        metrics = {
            "开盘": market_data.get("open_24h", 0),
            "最高": high,
            "最低": low,
            "前收盘": market_data.get("prev_close", 0)
        }
        cols = [col1, col2, col3, col4]
        for col, (label, value) in zip(cols, metrics.items()):
            with col:
                st.markdown(
                    f"<div style='text-align:center; padding:0.3rem; background:#1c2030; "
                    f"border-radius:4px; border:1px solid #2a2e39;'>"
                    f"<span style='font-size:0.6rem; color:#4f5564; text-transform:uppercase; "
                    f"letter-spacing:0.5px;'>{label}</span><br>"
                    f"<span style='font-weight:700; color:#d1d4dc; font-family:monospace; "
                    f"font-size:0.85rem;'>${format_price(value)}</span>"
                    f"</div>",
                    unsafe_allow_html=True
                )