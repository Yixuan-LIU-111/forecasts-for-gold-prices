"""英文新闻标题 → 简洁中文概括标题。

目标：把英文原标题替换为截图红框中的中文摘要式标题，让使用者一眼抓住核心。
策略：
  1. 优先调用 LLM（OpenAI）生成高质量中文概括；
  2. LLM 不可用时降级为规则模板，基于主体/动作/数值/影响快速生成；
  3. 标题本身已是中文时直接复用，避免重复处理。
"""
from __future__ import annotations

import logging
import re
from typing import Optional

from app.config import settings

logger = logging.getLogger(__name__)

# ---------- 主体识别 ----------
SUBJECT_RULES: list[tuple[list[str], str]] = [
    (["pboc", "people's bank of china", "china central bank"], "中国央行"),
    (["fed chair powell", "chairman powell", "jerome powell"], "美联储主席鲍威尔"),
    (["fed governor waller", "waller"], "美联储沃勒"),
    (["federal reserve", "fed"], "美联储"),
    (["core pce"], "核心PCE"),
    (["pce"], "PCE"),
    (["cpi"], "CPI"),
    (["jobless claims", "unemployment claims"], "美国初请失业金"),
    (["nonfarm payrolls", "payrolls"], "美国非农就业"),
    (["dxy", "dollar index"], "美元指数"),
    (["spdr", "gold etf holdings", "gold etf"], "SPDR黄金ETF持仓"),
    (["gold price", "gold spot", "spot gold", "xau/usd"], "黄金现货价格"),
    (["gold"], "黄金价格"),
    (["vix"], "VIX恐慌指数"),
    (["tips", "treasury yield", "10y yield"], "10年期TIPS收益率"),
    (["israel", "lebanon", "gaza", "middle east"], "中东局势"),
    (["geopolitical"], "地缘政治风险"),
]

# ---------- 动作/方向 ----------
UP_WORDS = ["rise", "rises", "rose", "rising", "up", "gain", "gains", "gained", "surge", "surges", "surged",
            "climb", "climbs", "climbed", "increase", "increased", "higher", "above", "break", "broke",
            "exceed", "exceeded", "soar", "soared", "jump", "jumped", "rally", "rallied", "反弹", "上涨"]
DOWN_WORDS = ["fall", "falls", "fell", "falling", "down", "drop", "drops", "dropped", "decline", "declines",
              "declined", "decrease", "decreased", "lower", "below", "slide", "slid", "sliding", "plunge",
              "plunged", "sink", "sank", "tumble", "tumbled", "下跌", "下滑", "回落"]

# ---------- 单位映射 ----------
UNIT_MAP: dict[str, str] = {
    "%": "%",
    "percent": "%",
    "tonnes": "吨",
    "tons": "吨",
    "tonne": "吨",
    "ton": "吨",
    "ounces": "盎司",
    "ounce": "盎司",
    "usd": "美元",
    "dollars": "美元",
    "dollar": "美元",
    "bp": "个基点",
    "basis points": "个基点",
    "basis point": "个基点",
}


def _is_chinese(text: str) -> bool:
    """标题中只要出现 CJK 汉字即视为已有中文标题，直接展示。"""
    return bool(re.search(r"[\u4e00-\u9fff]", text or ""))


def _detect_subject(text: str, topic: str = "") -> str:
    """根据关键词识别新闻主体。"""
    t = (text + " " + topic).lower()
    for keys, label in SUBJECT_RULES:
        if any(k in t for k in keys):
            return label
    topic_map = {
        "fed": "美联储",
        "inflation": "美国通胀",
        "geopolitical": "地缘局势",
        "gold": "黄金市场",
    }
    # 未知领域返回空，交由 rule_summarize 用通用实体兜底，避免一律“黄金市场”
    return topic_map.get(topic.lower(), "")


def _extract_action_value(text: str) -> tuple[str, str]:
    """提取动作方向与关键数值，返回 (动作, 数值)。"""
    t = text.lower()

    # 1) 找第一个“数字 + 可选单位”
    num_pat = re.compile(r"(\d+(?:\.\d+)?)\s*([a-z%]+)?", re.IGNORECASE)
    m = num_pat.search(text)
    value = ""
    if m:
        num = m.group(1)
        unit_raw = (m.group(2) or "").lower()
        # 仅识别已知单位或 %，避免把普通单词（如 near）当成单位
        unit = UNIT_MAP.get(unit_raw, "%" if unit_raw == "%" else "")
        value = f"{num}{unit}"

    # 2) 判断方向：优先看数字前面/附近的关键词
    prefix = text[:m.start()].lower() if m else t
    suffix = text[m.end():m.end()+20].lower() if m else ""
    combined = prefix + " " + suffix

    up = any(f" {w} " in f" {combined} " or combined.startswith(w + " ") for w in UP_WORDS)
    down = any(f" {w} " in f" {combined} " or combined.startswith(w + " ") for w in DOWN_WORDS)

    # 3) 根据方向 + 数值组合中文动作
    if value:
        if up:
            # 区分“突破/涨至/升至”
            if any(k in combined for k in ["above", "break", "broke", "exceed", "exceeded"]):
                return "突破", value
            return "上涨至", value
        if down:
            if any(k in combined for k in ["below", "drop to", "fell to"]):
                return "回落至", value
            return "下跌至", value
        # 有数值但无明显方向：用“为”
        return "为", value

    # 无数值，仅方向
    if up:
        return "上涨", ""
    if down:
        return "下跌", ""
    return "", ""


def _trim(s: str, max_len: int = 35) -> str:
    s = s.strip().rstrip("，,。.;")
    if len(s) > max_len:
        s = s[:max_len - 1] + "…"
    return s


# ---------- 关键句修饰语（呼应重点，如“创近一个月新高 / 低于预期”）----------
_QUALIFIER_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"highest (?:in|since)(?: a| one| the)? (month|week|year|decade)", re.I), "创近{unit}新高"),
    (re.compile(r"lowest (?:in|since)(?: a| one| the)? (month|week|year|decade)", re.I), "创近{unit}新低"),
    (re.compile(r"(\d+|one|two|three|four|five|six|seven|eight|nine|ten)[ -](?:week|month|year)[ -]low", re.I), "创{unit}新低"),
    (re.compile(r"(\d+|one|two|three|four|five|six|seven|eight|nine|ten)[ -](?:week|month|year)[ -]high", re.I), "创{unit}新高"),
    (re.compile(r"slightly below (?:the )?(?:forecast|estimate|expectations?)", re.I), "略低于预期"),
    (re.compile(r"below (?:the )?(?:forecast|estimate|expectations?)", re.I), "低于预期"),
    (re.compile(r"slightly above (?:the )?(?:forecast|estimate|expectations?)", re.I), "略高于预期"),
    (re.compile(r"above (?:the )?(?:forecast|estimate|expectations?)", re.I), "高于预期"),
    (re.compile(r"record (?:high|low)", re.I), "创纪录"),
]
_UNIT_ZH = {
    "month": "一个月", "week": "一周", "year": "一年", "decade": "十年",
    "one": "一个月", "two": "两周", "three": "三周", "four": "四周",
    "five": "五周", "six": "六周", "seven": "七周", "eight": "八周",
    "nine": "九周", "ten": "十周",
}


def _detect_qualifier(text: str) -> str:
    """从关键句中提取补充重点（最高/最低/预期差），让标题与关键句重点呼应。"""
    for pat, fmt in _QUALIFIER_PATTERNS:
        m = pat.search(text)
        if not m:
            continue
        if "{unit}" in fmt and m.groups():
            unit = _UNIT_ZH.get(m.group(1).lower(), m.group(1))
            return fmt.format(unit=unit)
        return fmt
    return ""


def rule_summarize(
    title: str,
    key_sentence: str = "",
    sentiment: str = "",
    topic: str = "",
) -> str:
    """规则模板生成中文标题（LLM 不可用时使用）。

    以关键句内容为核心，提炼核心事实（主体 + 动作 + 数值 + 补充重点），
    **不使用“利好/利空黄金”等单纯多空方向作为标题**，使标题呼应关键句重点。
    """
    text = (key_sentence or title).strip()
    subject = _detect_subject(text, topic)
    action, value = _extract_action_value(text)
    qualifier = _detect_qualifier(text)

    core = "".join(p for p in (subject, action, value) if p)
    if not core:
        # 完全无法解析时：尝试提取原标题中的专有主体（如 Meta / SpaceX / FBI），
        # 让标题至少点出“这是关于什么的新闻”，避免千篇一律的“黄金市场”。
        generic = _detect_generic_subject(text)
        if generic:
            return _trim(f"{generic} 相关动态")
        return _trim((subject or "黄金市场") + "相关动态")

    title_zh = core
    if qualifier:
        title_zh = core + "，" + qualifier
    return _trim(title_zh)


def _detect_generic_subject(text: str) -> str:
    """兜底：抓取英文标题开头的专有名词（人名/机构名，最多 3 个词）作为主体标签。"""
    m = re.match(r"((?:[A-Z][a-zA-Z0-9'.-]+(?:\s|$)){1,3})", (text or "").strip())
    if not m:
        return ""
    ent = m.group(1).strip()
    # 过滤过于泛化的开头词（避免把普通形容词当主体）
    if ent.lower() in {"the", "a", "an", "unpaid", "stock", "presidential"}:
        return ""
    return ent if len(ent) <= 30 else ""


def llm_summarize(title: str, key_sentence: str = "") -> Optional[str]:
    """调用 OpenAI 生成不超过 25 字的中文概括标题。"""
    if not settings.has_openai:
        return None
    try:
        from langchain_openai import ChatOpenAI
        from langchain_core.messages import HumanMessage, SystemMessage

        kwargs = dict(
            model=settings.openai_model,
            temperature=0,
            api_key=settings.openai_api_key,
            max_tokens=120,
        )
        # 兼容 OpenAI 兼容网关（如阿里云百炼 qwen 系列）
        if getattr(settings, "openai_base_url", ""):
            kwargs["base_url"] = settings.openai_base_url
        llm = ChatOpenAI(**kwargs)
        sys = SystemMessage(
            content=(
                "你是黄金市场新闻标题生成助手。请将下面的新闻（标题与关键句）概括成"
                "一条不超过25字、简洁通顺的中文标题。"
                "要求：1）用中文提炼新闻核心事实与关键数据，重点呼应关键句；"
                "2）不要使用“看多/看空/利好黄金/利空黄金”等单纯方向词作为标题；"
                '3）仅输出 JSON：{"title_zh":"..."}。'
            )
        )
        human = HumanMessage(content=f"标题: {title}\n关键句: {key_sentence or title}")
        resp = llm.invoke([sys, human])
        text = resp.content.strip()
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if not m:
            return None
        import json

        data = json.loads(m.group(0))
        zh = data.get("title_zh", "").strip()
        return zh if zh else None
    except Exception as e:  # noqa: BLE001
        logger.warning("LLM 中文标题生成失败，降级规则引擎: %s", e)
        return None


def summarize_title(
    title: str,
    key_sentence: str = "",
    sentiment: str = "",
    topic: str = "",
) -> str:
    """对外入口：中文标题直接复用；否则 LLM → 规则降级。"""
    if not title:
        return ""
    if _is_chinese(title):
        return _trim(title)

    zh = llm_summarize(title, key_sentence)
    if zh:
        return _trim(zh)
    return rule_summarize(title, key_sentence, sentiment, topic)


# 规则降级产出的低信息量标题特征：可在 LLM 可用时被升级重写
_BARE_DIRECTION = {"上涨", "下跌", "突破", "回落", "上涨至", "下跌至", "回落至"}


def _is_low_quality(zh: str) -> bool:
    """判断中文标题是否为规则兜底产出的低信息量文案（可被 LLM 结果覆盖）。

    仅命中「XX 相关动态」与裸方向词两类兜底模板；人工撰写的种子标题
    （如「SPDR黄金ETF持仓量增加2.5吨，创近一个月新高」）不会被误判。
    """
    s = (zh or "").strip()
    if not s:
        return True
    return s.endswith("相关动态") or s in _BARE_DIRECTION


def backfill_missing_title_zh(db, limit: int = 200) -> int:
    """补齐/升级 title_zh 中文概括标题，返回更新行数。

    背景：外部实时爬虫 news_scraper_llm 直接写共享的 news 表（见其 db.py
    `_get_or_create_news`），不产出 title_zh，会绕过 app 内的标题生成链路，
    导致前端出现英文标题。本函数作为**统一收口**，在爬取任务结束后补齐。

    处理范围（三类）：
      1. title_zh 为空 → 生成；
      2. title_zh 仍是英文（旧逻辑回退自 title）→ 重写为中文；
      3. title_zh 是规则兜底的低信息量文案且当前 LLM 可用 → 升级为 LLM 摘要。

    幂等：已是中文且非兜底模板的标题（含人工 demo 种子）一律跳过。
    """
    from sqlalchemy import select

    from app.models.database import News

    rows = (
        db.execute(select(News).order_by(News.id.desc()).limit(limit))
        .scalars()
        .all()
    )

    upgradable = settings.has_openai  # 无 LLM 时不重算兜底文案，避免无谓开销
    updated = 0
    for n in rows:
        current = (n.title_zh or "").strip()
        if current and _is_chinese(current):
            if not (upgradable and _is_low_quality(current)):
                continue  # 已是合格中文标题，保留原样
        zh = summarize_title(
            n.title or "", n.key_sentence or "", n.sentiment or "", n.topic or ""
        )
        if zh and zh != current:
            n.title_zh = zh
            updated += 1

    if updated:
        db.commit()
    return updated
