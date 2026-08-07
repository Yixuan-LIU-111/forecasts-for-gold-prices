"""
news_scraper_llm — 多站点新闻抓取 + LLM 情感分析

抓取目标（参考 docs/news_sample/ 截图红框标注区域）：
- 美联储官网 News & Events（Press Releases / Speeches / Testimony）
- 白宫官网 News 列表
- AP News 首页头条及 More Coverage
- CNN International 首页头条

输出：JSON + CSV，字段对齐「点时成金」仪表盘 news_list 组件。
"""

__version__ = "0.1.0"
