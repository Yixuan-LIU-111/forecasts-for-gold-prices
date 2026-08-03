"""
最新新闻列表组件
每条新闻附带情感标签、来源、时间、置信度
点击展开关键句和来源链接
"""
import streamlit as st

from app.dashboard.api.client import get_news
from app.dashboard.utils.helpers import (
    format_time_ago, get_sentiment_class, get_sentiment_icon, format_score
)


def render_news_list():
    """
    渲染最新新闻列表
    按时间倒序排列，支持展开查看详情
    """
    news = get_news(limit=20)

    if news is None:
        st.markdown(
            "<div class='placeholder-card'>暂无新闻数据</div>",
            unsafe_allow_html=True
        )
        return

    if not news:
        st.markdown(
            "<div class='placeholder-card'>暂无最新新闻</div>",
            unsafe_allow_html=True
        )
        return

    # 使用边框容器
    with st.container(border=True):
        # 总新闻数
        total = len(news)
        st.markdown(
            f"<div class='terminal-header'>最新新闻 (共 {total} 条)</div>",
            unsafe_allow_html=True
        )

        # 遍历渲染每条新闻
        for item in news:
            render_single_news(item)


def render_single_news(item: dict):
    """
    渲染单条新闻条目
    Args:
        item: 新闻数据字典
    """
    sentiment = item.get("sentiment", "neutral")
    sentiment_label = item.get("sentiment_label", "中性")
    title = item.get("title", "")
    source = item.get("source", "")
    published_at = item.get("published_at", "")
    confidence = item.get("confidence", 0)
    is_important = item.get("is_important", False)
    key_sentence = item.get("key_sentence", "")
    url = item.get("url", "")
    topic = item.get("topic", "")
    sentiment_score = item.get("sentiment_score", 0)
    hawk_dove = item.get("hawk_dove", None)
    hawk_dove_score = item.get("hawk_dove_score", None)

    # 情感标签 HTML
    icon = get_sentiment_icon(sentiment)
    badge_class = get_sentiment_class(sentiment)

    # 时间描述
    time_ago = format_time_ago(published_at)

    # 重要标记
    star = " ⭐" if is_important else ""

    # 构建新闻 HTML
    news_html = f"""
    <div class="news-item">
        <div class="news-title">
            <span class="sentiment-badge {badge_class}">{icon} {sentiment_label}</span>
            {title}{star}
        </div>
        <div class="news-meta">
            {source} | {time_ago} | 置信度: {confidence:.0%}
        </div>
    """

    # 展开详情（使用 st.expander 内嵌）
    with st.expander(f"📌 查看详情", expanded=False):
        if key_sentence:
            st.markdown(
                f"<div class='news-detail'>"
                f"<b style='color:#787b86; font-size:0.65rem; text-transform:uppercase; letter-spacing:0.5px;'>关键句</b><br>"
                f"<span style='color:#d1d4dc; font-size:0.75rem;'>{key_sentence}</span></div>",
                unsafe_allow_html=True
            )

        # 详细分析信息
        detail_parts = []
        detail_parts.append(f"情感分数: {format_score(sentiment_score)}")
        if topic:
            detail_parts.append(f"主题: {topic}")
        if hawk_dove:
            detail_parts.append(f"鹰鸽: {hawk_dove} ({format_score(hawk_dove_score)})")
        if url:
            detail_parts.append(f"<a href='{url}' target='_blank' style='color:#2962ff;'>查看原文 ↗</a>")

        st.markdown(
            f"<div style='font-size:0.65rem; color:#787b86; margin-top:0.3rem; font-family:monospace;'>"
            f"{' | '.join(detail_parts)}</div>",
            unsafe_allow_html=True
        )

    st.markdown("</div>", unsafe_allow_html=True)