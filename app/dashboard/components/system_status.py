"""
底部技术面板组件
显示系统运行状态、数据采集状态、API调用量、模型加载状态、设置入口
"""
import streamlit as st

from app.dashboard.api.client import get_system_status


def render_system_status():
    """
    渲染底部技术面板（优化P1: 添加容器边框）
    左：系统运行状态 | 右：设置入口
    """
    status = get_system_status()

    with st.container(border=True):
        col_left, col_right = st.columns([2, 1])

        with col_left:
            st.markdown("<b style='font-size:0.75rem; color:#787b86; text-transform:uppercase; letter-spacing:1px;'>系统运行状态</b>", unsafe_allow_html=True)

            # 状态项目
            status_items = [
                ("数据采集", status.get("data_collection", "正常"), "ok"),
                ("LLM 服务", status.get("llm_service", "正常"), "ok"),
                ("数据库连接", status.get("db_connection", "正常"), "ok"),
                ("模型加载", status.get("model_loaded", "LightGBM+XGBoost"), "ok"),
            ]

            # 2 列 x 2 行排列
            for i in range(0, len(status_items), 2):
                cols = st.columns(2)
                for col, (label, value, state) in zip(cols, status_items[i:i + 2]):
                    with col:
                        indicator_color = {"ok": "status-ok", "warn": "status-warn", "error": "status-error"}.get(state, "status-ok")
                        st.markdown(
                            f"<span style='font-size:0.7rem; font-family:monospace; color:#d1d4dc;'>"
                            f"<span class='status-indicator {indicator_color}'></span>"
                            f"{label}: <span style='color:#787b86;'>{value}</span></span>",
                            unsafe_allow_html=True
                        )

            # API 调用量
            api_usage = status.get("api_usage", {})
            if api_usage:
                today = api_usage.get("today", 0)
                limit = api_usage.get("limit", 100)
                name = api_usage.get("name", "")
                usage_pct = today / limit * 100 if limit > 0 else 0
                usage_class = "status-ok" if usage_pct < 50 else ("status-warn" if usage_pct < 80 else "status-error")
                bar_color = "#26a69a" if usage_pct < 50 else "#f0b90b" if usage_pct < 80 else "#ef5350"

                st.markdown(
                    f"<span style='font-size:0.7rem; font-family:monospace; color:#d1d4dc;'>"
                    f"<span class='status-indicator {usage_class}'></span>"
                    f"{name}: <span style='color:#787b86;'>{today}/{limit}</span> ({usage_pct:.0f}%)</span>"
                    f"<div style='background:#0a0e1a; border-radius:2px; height:3px; width:200px; margin-top:2px;'>"
                    f"<div style='background:{bar_color}; "
                    f"width:{usage_pct}%; height:3px; border-radius:2px;'></div></div>",
                    unsafe_allow_html=True
                )

        with col_right:
            st.markdown("<b style='font-size:0.75rem; color:#787b86; text-transform:uppercase; letter-spacing:1px;'>设置</b>", unsafe_allow_html=True)

            # 设置选项
            refresh_options = st.selectbox(
                "刷新频率",
                options=["30秒", "60秒", "120秒"],
                index=1,
                key="refresh_rate"
            )

            data_source = st.selectbox(
                "数据源",
                options=["实时", "演示"],
                index=0,
                key="data_source"
            )

            theme = st.selectbox(
                "主题",
                options=["浅色", "深色"],
                index=0,
                key="theme"
            )

            # 更新时间戳
            ts = status.get("timestamp", "")
            if ts:
                st.caption(f"状态更新: {ts[11:19] if len(ts) > 19 else ts}")