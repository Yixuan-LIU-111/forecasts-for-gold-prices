"""
回测面板组件
包含：回测参数配置、收益曲线、逐笔交易明细表
"""
import streamlit as st
import plotly.graph_objects as go
import plotly.express as px
import pandas as pd
from datetime import datetime, timedelta

from app.dashboard.api.client import get_backtest_results, run_backtest, get_trade_details
from app.dashboard.config import config
from app.dashboard.utils.helpers import format_pct, format_price


def render_backtest_panel():
    """
    渲染回测面板（优化P1: 添加容器边框）
    包含参数配置 + 收益曲线 + 逐笔交易明细
    """
    with st.container(border=True):
        st.markdown(
            "<div class='terminal-header'>模拟交易回测</div>",
            unsafe_allow_html=True
        )
        # 左侧：参数配置，右侧：收益曲线
        col_left, col_right = st.columns([1, 2])

        with col_left:
            render_backtest_params()

        with col_right:
            render_equity_curve()


def render_backtest_params():
    """
    渲染回测参数配置面板
    """
    st.markdown(
        "<div style='background:#1c2030; border-radius:4px; padding:0.8rem; border:1px solid #2a2e39;'>"
        "<b style='font-size:0.75rem; color:#787b86; text-transform:uppercase; letter-spacing:1px;'>回测参数设置</b>",
        unsafe_allow_html=True
    )

    # 日期范围
    today = datetime.now()
    default_start = today - timedelta(days=90)
    start_date = st.date_input("📅 起始日期", value=default_start)
    end_date = st.date_input("📅 结束日期", value=today - timedelta(days=1))

    # 资金和费用参数
    col1, col2 = st.columns(2)
    with col1:
        initial_capital = st.number_input("💰 初始资金 (USD)", value=10000, step=1000)
        spread = st.slider("📊 点差 (USD)", 0.1, 1.0, 0.3, 0.05)
    with col2:
        commission = st.slider("💵 手续费率 (%)", 0.0, 0.1, 0.01, 0.005)
        signal_threshold = st.slider("🎯 信号阈值", 0.50, 0.80, 0.55, 0.01)

    # 运行按钮
    if st.button("▶ 运行回测", width='stretch', type="primary"):
        with st.spinner("正在运行回测，请稍候..."):
            params = {
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
                "initial_capital": initial_capital,
                "spread": spread,
                "commission_pct": commission,
                "signal_threshold": signal_threshold
            }
            result = run_backtest(params)
            if result:
                st.success("✅ 回测完成！")
                st.session_state.backtest_result = result
            else:
                st.error("❌ 回测失败，请检查参数")

    st.markdown("</div>", unsafe_allow_html=True)


def render_equity_curve():
    """
    渲染收益曲线（含基准线对比）
    """
    # 获取回测结果（优先使用 session_state 中保存的）
    result = st.session_state.get("backtest_result") or get_backtest_results()

    if result is None:
        st.markdown(
            "<div class='placeholder-card'>请选择时间范围并运行回测</div>",
            unsafe_allow_html=True
        )
        return

    summary = result.get("summary", {})
    equity_curve = result.get("equity_curve", [])

    # 关键指标展示
    metrics = {
        "总收益率": format_pct(summary.get("total_return_pct", 0), 1),
        "夏普比率": f"{summary.get('sharpe_ratio', 0):.2f}",
        "最大回撤": format_pct(summary.get("max_drawdown_pct", 0), 1),
        "年化收益率": format_pct(summary.get("annual_return_pct", 0), 1),
        "胜率": format_pct(summary.get("win_rate", 0), 1),
        "盈亏比": f"{summary.get('profit_loss_ratio', 0):.2f}"
    }

    # 将指标分为两行显示
    metric_items = list(metrics.items())
    row1 = metric_items[:3]
    row2 = metric_items[3:]

    for row in [row1, row2]:
        cols = st.columns(3)
        for col, (label, value) in zip(cols, row):
            with col:
                # 颜色处理
                val_color = config.COLORS["bullish"] if value.startswith("+") else (
                    config.COLORS["bearish"] if value.startswith("-") else "#212121"
                )
                st.markdown(
                    f"<div class='metric-card'>"
                    f"<div class='metric-label'>{label}</div>"
                    f"<div class='metric-value' style='color:{val_color};'>{value}</div>"
                    f"</div>",
                    unsafe_allow_html=True
                )

    # 收益曲线图
    if equity_curve:
        df = pd.DataFrame(equity_curve)
        df["date"] = pd.to_datetime(df["date"])

        # 计算收益率百分比
        initial_capital = summary.get("initial_capital", 10000)
        df["strategy_return"] = (df["strategy"] / initial_capital - 1) * 100
        df["benchmark_return"] = (df["benchmark"] / initial_capital - 1) * 100

        fig = go.Figure()

        # 策略收益曲线
        fig.add_trace(go.Scatter(
            x=df["date"],
            y=df["strategy_return"],
            mode="lines",
            name="策略收益",
            line=dict(color=config.COLORS["chart_line"], width=2.5),
            hovertemplate="%{x|%m-%d}<br>策略: %{y:.2f}%<extra></extra>"
        ))

        # 基准线
        fig.add_trace(go.Scatter(
            x=df["date"],
            y=df["benchmark_return"],
            mode="lines",
            name="买入持有",
            line=dict(color="#787b86", width=1.5, dash="dash"),
            hovertemplate="%{x|%m-%d}<br>基准: %{y:.2f}%<extra></extra>"
        ))

        fig.update_layout(
            title={
                "text": "累计收益率对比",
                "font": {"size": 12, "color": "#787b86"},
                "x": 0,
                "xanchor": "left"
            },
            height=250,
            margin=dict(l=10, r=10, t=30, b=10),
            hovermode="x unified",
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1,
                        font={"color": "#787b86", "size": 10}),
            xaxis=dict(title="", showgrid=True, gridcolor="#1e222d", color="#787b86"),
            yaxis=dict(title="", showgrid=True, gridcolor="#1e222d", tickformat=".1f", color="#787b86"),
            paper_bgcolor="#131722",
            plot_bgcolor="#131722",
            font={"color": "#787b86", "size": 10, "family": "monospace"}
        )

        st.plotly_chart(fig, width='stretch', config={"displayModeBar": False})

    # 逐笔交易明细
    render_trade_details()


def render_trade_details():
    """
    渲染逐笔交易明细表
    """
    details = get_trade_details()

    if not details:
        return

    with st.expander("📋 查看逐笔交易明细", expanded=False):
        # 转换为 DataFrame
        df = pd.DataFrame(details)

        # 重命名列
        df_display = df.rename(columns={
            "trade_id": "序号",
            "open_time": "开仓时间",
            "direction": "方向",
            "open_price": "开仓价",
            "close_time": "平仓时间",
            "close_price": "平仓价",
            "pnl": "盈亏(USD)",
            "pnl_pct": "盈亏(%)",
            "signal_prob": "信号概率"
        })

        # 格式化列
        df_display["开仓价"] = df_display["开仓价"].apply(lambda x: f"${x:.2f}")
        df_display["平仓价"] = df_display["平仓价"].apply(lambda x: f"${x:.2f}")
        df_display["盈亏(USD)"] = df_display["盈亏(USD)"].apply(lambda x: f"${x:+.1f}")
        df_display["盈亏(%)"] = df_display["盈亏(%)"].apply(lambda x: f"{x:+.2f}%")
        df_display["信号概率"] = df_display["信号概率"].apply(lambda x: f"{x:.0%}")

        # 选择显示列
        display_cols = ["序号", "开仓时间", "方向", "开仓价", "平仓时间", "平仓价", "盈亏(USD)", "盈亏(%)", "信号概率"]

        # 使用 DataFrame 并添加条件格式
        st.dataframe(
            df_display[display_cols],
            width='stretch',
            hide_index=True,
            column_config={
                "盈亏(USD)": st.column_config.TextColumn(
                    "盈亏(USD)",
                    help="正值=盈利，负值=亏损"
                ),
                "方向": st.column_config.TextColumn(
                    "方向",
                    help="交易方向"
                )
            }
        )

        # 统计信息
        total_trades = len(details)
        win_trades = sum(1 for d in details if d.get("pnl", 0) > 0)
        loss_trades = sum(1 for d in details if d.get("pnl", 0) < 0)
        win_rate = win_trades / total_trades * 100 if total_trades > 0 else 0

        st.caption(
            f"共 {total_trades} 笔交易 | "
            f"盈利: {win_trades} 笔 | "
            f"亏损: {loss_trades} 笔 | "
            f"胜率: {win_rate:.1f}%"
        )