"""
LLM 情感分析器（编排层）

- 负责 prompt 组织与并发编排；底层 LLM 调用交由 llm_client.LLMClient 处理
  （含结构化输出、超时、失败重试、降级）。
- 支持两种模式：general（通用新闻正/负/中）、gold（黄金利多/利空）。
- 并发通过 asyncio.Semaphore 控制，单条失败不影响整体流水线。

输入：RawNewsItem（抓取后、分析前）
输出：SentimentResult（结构化情感分数 / 标签 / 主题 / 置信度 / 关键句）
"""
import asyncio
from typing import Sequence

from .config import settings
from .llm_client import LLMClient
from .models import RawNewsItem, SentimentResult


# ------------------ Prompts ------------------

_GENERAL_SYSTEM = """你是一名通用新闻情感分析专家。请分析以下新闻标题与摘要，判断其整体情感倾向。

输出 JSON 格式（注意：下面仅为格式示例，不要当作模板变量）：
{{
  "sentiment_score": float,   // -1（强烈负向）~ +1（强烈正向）
  "sentiment_label": string,  // "positive" | "negative" | "neutral"
  "topic": string,            // 新闻主题，如 Politics, Economy, Military, Diplomacy, Technology, Other
  "confidence": float,        // 0~1
  "key_sentence": string      // 支撑判断的关键句（最多一句原文或概括）
}}

判断规则：
- 明显正面事件（突破、合作、利好经济、和平协议等）→ 正向
- 明显负面事件（冲突、危机、制裁、衰退、灾难等）→ 负向
- 事实陈述、数据发布、无明显褒贬 → 中性
- 无法判断 → 中性，confidence 给低值
"""

_GOLD_SYSTEM = """你是黄金市场新闻情感分析专家。分析以下新闻对黄金价格（XAU/USD）的影响。

输出 JSON 格式（注意：下面仅为格式示例，不要当作模板变量）：
{{
  "sentiment_score": float,   // -1（强烈利空黄金）~ +1（强烈利多黄金）
  "sentiment_label": string,  // "positive" | "negative" | "neutral"
  "topic": string,            // Fed / Inflation / Geopolitical / Dollar / Other
  "confidence": float,        // 0~1
  "key_sentence": string      // 影响判断的关键句
}}

判断规则（§9.2）：
- 美联储加息/鹰派 → 利空黄金（负分）
- 美联储降息/鸽派 → 利多黄金（正分）
- 地缘冲突升级 → 避险需求上升 → 利多黄金
- 美元升值 → 利空黄金
- 通胀超预期 → 黄金保值需求上升 → 利多黄金

离散标签映射：
- score > 0.15  → "positive"（利多）
- score < -0.15 → "negative"（利空）
- 否则           → "neutral"（中性）
"""

_HUMAN_TEMPLATE = """标题：{title}
摘要：{summary}
来源：{source}
发布时间：{published_at}

请输出 JSON："""


class SentimentAnalyzer:
    """LLM 情感分析器（编排层，底层调用见 llm_client.LLMClient）"""

    def __init__(self):
        self.mode = settings.sentiment_mode
        # 底层 LLM 调用封装（含重试/超时/降级），并暴露 model_version 供落库去重
        self.client = LLMClient()
        self._semaphore = asyncio.Semaphore(settings.llm_max_concurrency)

    # ---------------- 工具 ----------------

    @staticmethod
    def _system_prompt(mode: str) -> str:
        return _GOLD_SYSTEM if mode == "gold" else _GENERAL_SYSTEM

    @staticmethod
    def _inputs(item: RawNewsItem) -> dict:
        return {
            "title": item.title,
            "summary": item.summary or "",
            "source": item.source,
            "published_at": item.published_at or "",
        }

    # ---------------- 公共接口 ----------------

    async def analyze_one(self, item: RawNewsItem) -> SentimentResult:
        """单条新闻异步分析（结构化优先 → 手动解析兜底 → 中性降级均由 LLMClient 完成）。"""
        async with self._semaphore:
            try:
                return await self.client.analyze(
                    self._system_prompt(self.mode),
                    _HUMAN_TEMPLATE,
                    self._inputs(item),
                )
            except Exception as exc:
                # LLMClient 已内部降级；此处仅兜底极端编排异常
                return SentimentResult(
                    sentiment_score=0.0,
                    sentiment_label="neutral",
                    topic="Other",
                    confidence=0.0,
                    key_sentence=f"分析编排异常: {exc}",
                )

    async def analyze_many(
        self, items: Sequence[RawNewsItem]
    ) -> list[tuple[RawNewsItem, SentimentResult, str]]:
        """并发分析多条新闻。

        Returns:
            [(item, sentiment, model_version), ...]
            model_version 用于落库去重键（news_id + model_version + mode）。
        """
        tasks = [self.analyze_one(item) for item in items]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        out: list[tuple[RawNewsItem, SentimentResult, str]] = []
        for item, res in zip(items, results):
            if isinstance(res, SentimentResult):
                out.append((item, res, self.client.model_version))
            else:
                out.append((
                    item,
                    SentimentResult(
                        sentiment_score=0.0,
                        sentiment_label="neutral",
                        topic="Other",
                        confidence=0.0,
                        key_sentence=f"异常: {res}",
                    ),
                    self.client.model_version,
                ))
        return out
