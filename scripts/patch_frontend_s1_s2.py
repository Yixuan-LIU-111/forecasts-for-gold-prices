"""前端页面优化补丁 S1/S2：移除功能点编号(F-code)、修正失实表述。

对应 docs/前端页面优化.docx 建议 1、2。
执行：python scripts/patch_frontend_s1_s2.py
"""
from pathlib import Path
import sys

HTML = Path(__file__).resolve().parent.parent / "frontend" / "dashboard.html"

# (old, new, 期望命中次数)
REPLACEMENTS: list[tuple[str, str, int]] = [
    # ---------- S1 侧栏导航：删除 F 编号 ----------
    ('<button class="active" data-view="dashboard"><span class="ico"></span>仪表盘<span class="code">F09</span></button>',
     '<button class="active" data-view="dashboard"><span class="ico"></span>仪表盘<span class="code">监测</span></button>', 1),
    ('<button data-view="news"><span class="ico"></span>新闻中心<span class="code">F01·04·05</span></button>',
     '<button data-view="news"><span class="ico"></span>新闻中心<span class="code">资讯</span></button>', 1),
    ('<button data-view="backtest"><span class="ico"></span>回测分析<span class="code">F10</span></button>',
     '<button data-view="backtest"><span class="ico"></span>回测分析<span class="code">回测</span></button>', 1),
    ('<button data-view="stats"><span class="ico"></span>准确率统计<span class="code">F11</span></button>',
     '<button data-view="stats"><span class="ico"></span>准确率统计<span class="code">统计</span></button>', 1),
    ('<button data-view="settings"><span class="ico"></span>系统设置<span class="code">F01·07·08</span></button>',
     '<button data-view="settings"><span class="ico"></span>系统设置<span class="code">配置</span></button>', 1),

    # ---------- S1 面包屑 ----------
    ('<span class="crumb" id="pageCrumb">可视化仪表盘 · F09</span>',
     '<span class="crumb" id="pageCrumb">可视化仪表盘</span>', 1),

    # ---------- S1 视图注释与分区标注 ----------
    ('视图 1 · 仪表盘（F09）—— 监测中枢', '视图 1 · 仪表盘 —— 监测中枢', 1),
    ('<!-- ① 实时行情（F02） -->', '<!-- ① 实时行情 -->', 1),
    ('<span class="band-meta">F02 · 市场数据采集</span>', '<span class="band-meta">市场数据采集</span>', 1),
    ('<!-- ② 信号决策（F08·F10） -->', '<!-- ② 信号决策 -->', 1),
    ('<span class="band-meta">F08·F10 · 信号生成 + 多空评分</span>',
     '<span class="band-meta">信号生成 + 多空评分</span>', 1),
    ('<!-- ③ 资讯情绪（F01·F04） -->', '<!-- ③ 资讯情绪 -->', 1),
    ('<span class="band-meta">F01·F04 · 新闻采集 + 情感分析</span>',
     '<span class="band-meta">新闻采集 + 情感分析</span>', 1),
    ('<!-- ④ 因子监控（F02·F04·F05） -->', '<!-- ④ 因子监控 -->', 1),
    ('<span class="band-meta">F02·F04·F05 · 实时因子面板</span>',
     '<span class="band-meta">实时因子面板</span>', 1),
    ('<!-- ⑤ 绩效速览（F11·F10 概览） -->', '<!-- ⑤ 绩效速览 -->', 1),
    ('<span class="band-meta">F11·F10 · 概览（详情见对应模块）</span>',
     '<span class="band-meta">概览（详情见对应模块）</span>', 1),
    ('视图 2 · 新闻中心（F01·F04·F05）', '视图 2 · 新闻中心', 1),
    ('<span class="band-meta">F01 · 新闻数据采集</span>', '<span class="band-meta">新闻数据采集</span>', 1),
    ('<span class="band-meta">F04 · LLM 情感分析</span>', '<span class="band-meta">新闻情感分析</span>', 1),
    ('<span class="band-meta">F05 · 货币政策预期</span>', '<span class="band-meta">货币政策预期</span>', 1),
    ('视图 3 · 回测分析（F10）', '视图 3 · 回测分析', 1),
    ('<span class="band-meta">F10 · Backtrader</span>', '<span class="band-meta">参数配置</span>', 1),
    ('<span class="band-meta">F10 · 输出指标</span>', '<span class="band-meta">输出指标</span>', 1),
    ('<span class="band-meta">F10 · 权益曲线</span>', '<span class="band-meta">权益曲线</span>', 1),
    ('视图 4 · 准确率统计（F11）', '视图 4 · 准确率统计', 1),
    ('<span class="band-meta">F11 · 7d / 30d</span>', '<span class="band-meta">7d / 30d</span>', 1),
    ('<span class="band-meta">F11 · 信号方向</span>', '<span class="band-meta">信号方向</span>', 1),
    ('<span class="band-meta">F11 · 买入持有</span>', '<span class="band-meta">买入持有</span>', 1),
    ('视图 5 · 系统设置（F01/F02 数据源 + F04/F05/F07 模型 + F08 信号 + 监控）',
     '视图 5 · 系统设置（数据源 + 模型 + 信号 + 监控）', 1),
    ('<span class="band-meta">F01·F02 · 采集</span>', '<span class="band-meta">采集配置</span>', 1),
    ('<span class="band-meta">F04·F05·F07 · 推理</span>', '<span class="band-meta">推理配置</span>', 1),
    ('<span class="band-meta">F08 · 信号生成器</span>', '<span class="band-meta">信号生成器</span>', 1),

    # ---------- S1 视图名映射（JS） ----------
    ("dashboard:['实时仪表盘','可视化仪表盘 · F09'],",
     "dashboard:['实时仪表盘','可视化仪表盘'],", 1),
    ("news:['新闻中心','新闻采集 / 情感分析 / 鹰鸽指数 · F01·F04·F05'],",
     "news:['新闻中心','新闻采集 / 情感分析 / 鹰鸽指数'],", 1),
    ("backtest:['回测分析','模拟交易回测 · F10'],",
     "backtest:['回测分析','模拟交易回测'],", 1),
    ("stats:['准确率统计','历史准确率统计 · F11'],",
     "stats:['准确率统计','历史准确率统计'],", 1),
    ("settings:['系统设置','数据源 / 模型 / 信号 / 监控 · F01·F07·F08']",
     "settings:['系统设置','数据源 / 模型 / 信号 / 监控']", 1),

    # ---------- S2 修正失实表述 ----------
    ('<p class="band-note">XAU/USD 分钟级实时价格与关联指标，源自 yfinance（GC=F / DX-Y.NYB / ^VIX），Plotly 折线图每 1 分钟刷新。</p>',
     '<p class="band-note">XAU/USD 分钟级实时价格与关联指标：行情与美元指数来自新浪财经，VIX 来自 CBOE，10Y 实际利率来自 FRED（DFII10）。Plotly 折线图随页面刷新周期更新，具体数据源见「系统设置 · 数据源配置」。</p>', 1),
    ('<p class="band-note">最新黄金相关新闻与 LLM 情感标签（红=利多、绿=利空、灰=中性）。新闻经 NewsAPI 采集、LangChain+GPT-4o-mini 输出 sentiment_score / topic / confidence。</p>',
     '<p class="band-note">最新黄金相关新闻与情感标签（红=利多、绿=利空、灰=中性）。当前演示环境由内置规则引擎产出 sentiment_score / topic / confidence；生产环境接入 NewsAPI / GNews 采集与 LLM 情感分析，LLM 不可用时自动降级为规则引擎。点击标题可跳转原文。</p>', 1),
    ('<p class="band-note">LangChain + GPT-4o-mini 对每条新闻输出 sentiment_score（-1~+1）、topic、confidence、key_sentence；LLM 超时降级为规则引擎。</p>',
     '<p class="band-note">对每条新闻输出 sentiment_score（-1~+1）、topic、confidence、key_sentence。当前演示环境由规则引擎计算；生产环境优先调用 LLM，超时或失败时自动降级为规则引擎。实际状态见「系统设置 · 模型配置」。</p>', 1),
]


def main() -> int:
    text = HTML.read_text(encoding="utf-8")
    failed = []
    for old, new, expect in REPLACEMENTS:
        cnt = text.count(old)
        if cnt != expect:
            failed.append((old[:70], cnt, expect))
            continue
        text = text.replace(old, new)
    if failed:
        print("以下替换未命中预期次数，已中止：")
        for o, c, e in failed:
            print(f"  actual={c} expect={e} :: {o}")
        return 1
    HTML.write_text(text, encoding="utf-8")
    print(f"OK: 应用 {len(REPLACEMENTS)} 处替换 -> {HTML}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
