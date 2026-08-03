"""
自定义 CSS 样式 — Wind/Bloomberg 终端风格
深色主题 · 高数据密度 · 等宽数字 · 专业金融配色
"""

CUSTOM_CSS = """
<style>
    /* ========== 全局变量 ========== */
    :root {
        --bg-primary: #0a0e1a;
        --bg-secondary: #131722;
        --bg-tertiary: #1c2030;
        --bg-hover: #232838;
        --border-color: #2a2e39;
        --border-light: #1e222d;
        --text-primary: #d1d4dc;
        --text-secondary: #787b86;
        --text-muted: #4f5564;
        --accent-gold: #f0b90b;
        --accent-blue: #2962ff;
        --color-up: #26a69a;
        --color-down: #ef5350;
        --color-neutral: #787b86;
        --font-mono: 'SF Mono', 'Fira Code', 'JetBrains Mono', 'Consolas', 'Monaco', monospace;
        --font-sans: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', sans-serif;
    }

    /* ========== 全局背景 ========== */
    .stApp {
        background: var(--bg-primary);
    }
    /* 移除 Streamlit 默认顶部 padding */
    .stApp > header {
        background: var(--bg-primary);
        border-bottom: 1px solid var(--border-color);
    }
    /* 全局文字颜色 */
    .stApp, .stMarkdown, .stText {
        color: var(--text-primary);
        font-family: var(--font-sans);
    }

    /* ========== Streamlit 原生组件深色覆盖 ========== */
    /* 容器边框 */
    .stContainer[data-testid="stVerticalBlockBorderWrapper"] {
        border: 1px solid var(--border-color) !important;
        border-radius: 4px !important;
        background: var(--bg-secondary) !important;
    }
    /* 侧边栏 */
    section[data-testid="stSidebar"] {
        background: var(--bg-secondary);
        border-right: 1px solid var(--border-color);
    }
    section[data-testid="stSidebar"] .stMarkdown, 
    section[data-testid="stSidebar"] label {
        color: var(--text-secondary);
    }
    /* radio 按钮 */
    .stRadio > div[role="radiogroup"] label {
        color: var(--text-primary) !important;
        font-size: 0.85rem !important;
        padding: 0.4rem 0.6rem !important;
        border-radius: 3px;
        transition: background 0.15s;
    }
    .stRadio > div[role="radiogroup"] label:hover {
        background: var(--bg-tertiary);
    }
    .stRadio > div[role="radiogroup"] label[data-checked="true"] {
        color: var(--accent-gold) !important;
        background: var(--bg-tertiary);
    }
    /* selectbox / number_input / date_input 深色 */
    .stSelectbox, .stNumberInput, .stDateInput {
        background: transparent;
    }
    .stSelectbox > div > div, 
    .stNumberInput > div > div,
    .stDateInput > div > div {
        background: var(--bg-tertiary) !important;
        border: 1px solid var(--border-color) !important;
        border-radius: 3px !important;
        color: var(--text-primary) !important;
    }
    .stSelectbox > div > div > div,
    .stNumberInput input,
    .stDateInput input {
        color: var(--text-primary) !important;
        font-family: var(--font-mono) !important;
        font-size: 0.8rem !important;
    }
    /* 按钮 */
    .stButton > button {
        background: var(--accent-blue) !important;
        color: white !important;
        border: none !important;
        border-radius: 3px !important;
        font-size: 0.8rem !important;
        font-weight: 600 !important;
        padding: 0.4rem 1rem !important;
        transition: opacity 0.15s;
    }
    .stButton > button:hover {
        opacity: 0.85;
    }
    .stButton > button[kind="secondary"] {
        background: var(--bg-tertiary) !important;
        border: 1px solid var(--border-color) !important;
        color: var(--text-primary) !important;
    }
    /* expander */
    .stExpander {
        background: var(--bg-secondary) !important;
        border: 1px solid var(--border-color) !important;
        border-radius: 4px !important;
    }
    .stExpander > details > summary {
        color: var(--text-secondary) !important;
        font-size: 0.8rem !important;
    }
    .stExpander > details > summary:hover {
        color: var(--text-primary) !important;
    }
    /* slider */
    .stSlider > div > div > div > div {
        background: var(--accent-blue) !important;
    }
    /* caption */
    .stCaption, p.caption {
        color: var(--text-muted) !important;
        font-size: 0.7rem !important;
    }
    /* 分隔线 */
    hr {
        border-color: var(--border-light) !important;
        margin: 0.5rem 0 !important;
    }
    /* DataFrame 表格 */
    .stDataFrame {
        background: var(--bg-secondary);
    }
    .stDataFrame table {
        color: var(--text-primary);
    }
    .stDataFrame thead th {
        background: var(--bg-tertiary) !important;
        color: var(--text-secondary) !important;
        font-size: 0.75rem !important;
        text-transform: uppercase;
        letter-spacing: 0.5px;
    }
    .stDataFrame tbody td {
        font-family: var(--font-mono);
        font-size: 0.8rem;
    }

    /* ========== 终端标题样式 ========== */
    .terminal-header {
        font-size: 0.7rem;
        font-weight: 700;
        color: var(--text-secondary);
        text-transform: uppercase;
        letter-spacing: 1.5px;
        padding: 0.3rem 0;
        margin-bottom: 0.3rem;
        border-bottom: 1px solid var(--border-color);
        display: flex;
        align-items: center;
        gap: 0.3rem;
    }
    .terminal-header::before {
        content: "";
        width: 3px;
        height: 12px;
        background: var(--accent-gold);
        border-radius: 1px;
    }

    /* ========== 信号卡片 ========== */
    .signal-card {
        background: var(--bg-tertiary);
        border-radius: 4px;
        padding: 0.7rem;
        text-align: center;
        height: 100%;
        border: 1px solid var(--border-color);
        border-left: 3px solid var(--text-muted);
        transition: border-color 0.2s;
    }
    .signal-card:hover {
        border-color: var(--text-muted);
    }
    .signal-card .label {
        font-size: 0.6rem;
        color: var(--text-muted);
        text-transform: uppercase;
        letter-spacing: 1px;
        margin-bottom: 0.3rem;
        font-family: var(--font-sans);
    }
    .signal-card .value {
        font-size: 1.3rem;
        font-weight: 700;
        margin: 0.2rem 0;
        font-family: var(--font-mono);
    }
    .signal-card .sub-text {
        font-size: 0.65rem;
        color: var(--text-secondary);
        font-family: var(--font-mono);
    }

    /* 方向卡片 — 看涨 */
    .signal-bullish {
        background: linear-gradient(135deg, rgba(38,166,154,0.15) 0%, rgba(38,166,154,0.05) 100%);
        border-left: 3px solid var(--color-up);
        color: var(--color-up);
    }
    .signal-bullish .value { color: var(--color-up); }
    /* 方向卡片 — 看跌 */
    .signal-bearish {
        background: linear-gradient(135deg, rgba(239,83,80,0.15) 0%, rgba(239,83,80,0.05) 100%);
        border-left: 3px solid var(--color-down);
        color: var(--color-down);
    }
    .signal-bearish .value { color: var(--color-down); }
    /* 方向卡片 — 观望 */
    .signal-neutral {
        background: linear-gradient(135deg, rgba(120,123,134,0.12) 0%, rgba(120,123,134,0.04) 100%);
        border-left: 3px solid var(--color-neutral);
        color: var(--color-neutral);
    }
    .signal-neutral .value { color: var(--color-neutral); }

    /* ========== 因子卡片 ========== */
    .factor-card {
        background: var(--bg-tertiary);
        border-radius: 4px;
        padding: 0.5rem 0.7rem;
        border: 1px solid var(--border-color);
        height: 100%;
    }
    .factor-card:hover {
        border-color: var(--text-muted);
    }
    .factor-card .factor-name {
        font-size: 0.6rem;
        color: var(--text-muted);
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.5px;
    }
    .factor-card .factor-value {
        font-size: 1rem;
        font-weight: 700;
        margin: 0.1rem 0;
        font-family: var(--font-mono);
        color: var(--text-primary);
    }
    .factor-card .factor-change {
        font-size: 0.65rem;
        font-family: var(--font-mono);
    }
    .factor-card .factor-source {
        font-size: 0.55rem;
        color: var(--text-muted);
        font-family: var(--font-mono);
        margin-top: 0.1rem;
    }

    /* ========== 趋势颜色 ========== */
    .trend-up { color: var(--color-up); }
    .trend-down { color: var(--color-down); }
    .trend-flat { color: var(--color-neutral); }

    /* ========== 新闻列表 ========== */
    .news-item {
        padding: 0.5rem 0.7rem;
        border-bottom: 1px solid var(--border-light);
        transition: background 0.15s;
    }
    .news-item:hover {
        background: var(--bg-tertiary);
    }
    .news-item .news-title {
        font-size: 0.8rem;
        font-weight: 500;
        color: var(--text-primary);
        line-height: 1.4;
    }
    .news-item .news-meta {
        font-size: 0.6rem;
        color: var(--text-muted);
        margin-top: 0.15rem;
        font-family: var(--font-mono);
    }
    .news-item .news-detail {
        font-size: 0.7rem;
        color: var(--text-secondary);
        margin-top: 0.3rem;
        padding: 0.4rem;
        background: var(--bg-tertiary);
        border-radius: 3px;
        border-left: 2px solid var(--border-color);
    }

    /* ========== 情感标签 ========== */
    .sentiment-badge {
        display: inline-block;
        padding: 0.1rem 0.4rem;
        border-radius: 2px;
        font-size: 0.6rem;
        font-weight: 700;
        text-transform: uppercase;
        letter-spacing: 0.5px;
        font-family: var(--font-sans);
    }
    .sentiment-bullish {
        background: rgba(38,166,154,0.15);
        color: var(--color-up);
        border: 1px solid rgba(38,166,154,0.3);
    }
    .sentiment-bearish {
        background: rgba(239,83,80,0.15);
        color: var(--color-down);
        border: 1px solid rgba(239,83,80,0.3);
    }
    .sentiment-neutral {
        background: rgba(120,123,134,0.12);
        color: var(--color-neutral);
        border: 1px solid rgba(120,123,134,0.25);
    }

    /* ========== 状态指示器 ========== */
    .status-indicator {
        display: inline-block;
        width: 8px;
        height: 8px;
        border-radius: 50%;
        margin-right: 0.3rem;
        vertical-align: middle;
    }
    .status-ok { background: var(--color-up); box-shadow: 0 0 6px rgba(38,166,154,0.4); }
    .status-warn { background: var(--accent-gold); box-shadow: 0 0 6px rgba(240,185,11,0.4); }
    .status-error { background: var(--color-down); box-shadow: 0 0 6px rgba(239,83,80,0.4); }

    /* ========== 回测指标卡片 ========== */
    .metric-card {
        background: var(--bg-tertiary);
        border-radius: 4px;
        padding: 0.4rem 0.6rem;
        border: 1px solid var(--border-color);
        text-align: center;
    }
    .metric-card .metric-label {
        font-size: 0.6rem;
        color: var(--text-muted);
        text-transform: uppercase;
        letter-spacing: 0.5px;
    }
    .metric-card .metric-value {
        font-size: 1.1rem;
        font-weight: 700;
        font-family: var(--font-mono);
    }

    /* ========== 占位符 ========== */
    .placeholder-card {
        background: var(--bg-secondary);
        border-radius: 4px;
        padding: 1.5rem;
        text-align: center;
        color: var(--text-muted);
        border: 1px dashed var(--border-color);
        font-size: 0.8rem;
    }

    /* ========== 仪表盘说明 ========== */
    .dashboard-desc {
        font-size: 0.75rem;
        color: var(--text-secondary);
        line-height: 1.6;
        padding: 0.6rem 0.8rem;
        background: var(--bg-secondary);
        border-radius: 4px;
        border-left: 3px solid var(--accent-gold);
        margin-bottom: 0.5rem;
    }
    .dashboard-desc strong {
        color: var(--accent-gold);
    }

    /* ========== 侧边栏导航 ========== */
    .nav-logo {
        text-align: center;
        padding: 0.8rem 0 0.5rem;
    }
    .nav-logo .logo-icon {
        font-size: 1.5rem;
    }
    .nav-logo .logo-title {
        font-size: 0.95rem;
        font-weight: 700;
        color: var(--accent-gold);
        margin-top: 0.2rem;
        letter-spacing: 1px;
    }
    .nav-logo .logo-subtitle {
        font-size: 0.6rem;
        color: var(--text-muted);
        text-transform: uppercase;
        letter-spacing: 1px;
    }
    .nav-footer {
        font-size: 0.6rem;
        color: var(--text-muted);
        text-align: center;
        padding: 0.8rem 0;
        border-top: 1px solid var(--border-color);
        margin-top: 0.8rem;
        font-family: var(--font-mono);
    }

    /* ========== 时间筛选器 ========== */
    .time-filter-row {
        display: flex;
        align-items: center;
        gap: 0.5rem;
        margin-bottom: 0.3rem;
    }
    .time-filter-row .filter-label {
        font-size: 0.7rem;
        color: var(--text-muted);
        font-weight: 600;
        white-space: nowrap;
        text-transform: uppercase;
        letter-spacing: 0.5px;
    }

    /* ========== 终端状态栏 ========== */
    .terminal-statusbar {
        background: var(--bg-secondary);
        border: 1px solid var(--border-color);
        border-radius: 4px;
        padding: 0.4rem 0.7rem;
        display: flex;
        align-items: center;
        gap: 1rem;
        font-size: 0.7rem;
        font-family: var(--font-mono);
        color: var(--text-secondary);
        margin-bottom: 0.5rem;
    }
    .terminal-statusbar .ts-item {
        display: flex;
        align-items: center;
        gap: 0.3rem;
    }
    .terminal-statusbar .ts-divider {
        width: 1px;
        height: 12px;
        background: var(--border-color);
    }

    /* ========== 响应式 ========== */
    @media (max-width: 768px) {
        .signal-card .value {
            font-size: 1rem;
        }
        .factor-card .factor-value {
            font-size: 0.85rem;
        }
    }
</style>
"""


def inject_css():
    """注入自定义 CSS 到 Streamlit 页面"""
    import streamlit as st
    st.markdown(CUSTOM_CSS, unsafe_allow_html=True)


def signal_card_html(direction: str, direction_en: str, confidence: str) -> str:
    """
    生成方向信号卡片的 HTML（终端风格）
    Args:
        direction: 中文方向 (看涨/看跌/观望)
        direction_en: 英文方向 (bullish/bearish/neutral)
        confidence: 置信度 (高/中/低)
    Returns:
        HTML 字符串
    """
    css_class = {
        "看涨": "signal-bullish",
        "看跌": "signal-bearish",
        "观望": "signal-neutral"
    }.get(direction, "signal-neutral")

    icon = {
        "看涨": "▲",
        "看跌": "▼",
        "观望": "■"
    }.get(direction, "■")

    return f"""
    <div class="signal-card {css_class}">
        <div class="label">信号方向</div>
        <div class="value">{icon} {direction}</div>
        <div class="sub-text">置信度: {confidence}</div>
    </div>
    """
