"""
顶部状态栏组件 — 终端风格
显示系统运行状态、SSE连接状态、当前时间、刷新倒计时、演示模式开关
"""
from datetime import datetime

import streamlit as st

from app.dashboard.api.client import get_system_status


def render_status_bar():
    """
    渲染顶部状态栏（终端风格 — 紧凑单行布局）
    """
    # 获取系统状态
    status = get_system_status()

    # 系统运行状态指示灯
    status_color = {
        "ok": "status-ok",
        "warn": "status-warn",
        "error": "status-error"
    }.get(status.get("status", "ok"), "status-ok")

    data_status = status.get("data_collection", "正常")

    # 当前时间
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # 演示模式标识
    mode = status.get("mode", "演示模式")
    mode_class = "status-warn" if "演示" in mode else "status-ok"

    # 终端风格状态栏 — 单行紧凑布局
    st.markdown(
        f"""
        <div class="terminal-statusbar">
            <div class="ts-item">
                <span class="status-indicator {status_color}"></span>
                <span>SYSTEM {data_status}</span>
            </div>
            <div class="ts-divider"></div>
            <div class="ts-item">
                <span class="status-indicator status-ok"></span>
                <span>SIGNAL LIVE</span>
            </div>
            <div class="ts-divider"></div>
            <div class="ts-item">
                <span>🕐 {now}</span>
            </div>
            <div class="ts-divider"></div>
            <div class="ts-item">
                <span class="status-indicator {mode_class}"></span>
                <span>{mode}</span>
            </div>
            <div class="ts-divider"></div>
            <div class="ts-item">
                <span style="color:#4f5564;">AUTO-REFRESH 60s</span>
            </div>
        </div>
        """,
        unsafe_allow_html=True
    )
