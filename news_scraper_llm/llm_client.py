"""
LLM 调用封装层（需求 3：接口与调用层）

职责边界：本层只负责「把一条新闻交给 LLM 并得到结构化情感结果」，
不涉及抓取、并发编排与落库。上层（analyzer）负责 prompt 组织与编排。

能力：
- 调用 OpenAI 兼容端点（qwen-turbo 等免费模型）；
- 结构化输出（json_mode）优先，普通文本链 + 手动解析兜底；
- 超时（ChatOpenAI timeout）与异常捕获；
- 失败重试（指数退避，次数可配），全部失败后降级为中性低置信；
- 返回使用的模型版本，供落库去重与溯源。

任何单条失败都不会抛出，保证上游「抓取 → 分析 → 落库」流水线不中断。
"""
import asyncio
import json
import logging
import re
from typing import Any

from langchain_core.messages import AIMessage
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate

from .config import settings
from .models import SentimentResult

logger = logging.getLogger(__name__)

# 中性标签阈值（与 analyzer 的 prompt 定义保持一致，用于兜底时按分值推断标签）
_POS_THRESHOLD = 0.15
_NEG_THRESHOLD = -0.15


class LLMClient:
    """对单条新闻调用 LLM 并解析为 SentimentResult。

    线程/协程安全：ChatOpenAI 实例可被并发 ainvoke；本类的 analyze 为纯函数式
    （仅读取 self 配置），无共享可变状态，可安全配合 asyncio.Semaphore 并发调用。
    """

    def __init__(
        self,
        model: str | None = None,
        base_url: str | None = None,
        api_key: str | None = None,
        temperature: float | None = None,
        timeout: int | None = None,
        max_retries: int | None = None,
        retry_backoff_s: float | None = None,
    ):
        self.model = model or settings.openai_model
        self.model_version = self.model  # 落库去重键 + 溯源：例如 "qwen-turbo"
        self.max_retries = (
            settings.llm_max_retries if max_retries is None else max_retries
        )
        self.retry_backoff_s = (
            settings.llm_retry_backoff_s if retry_backoff_s is None else retry_backoff_s
        )

        self.llm = ChatOpenAI(
            model=self.model,
            temperature=settings.openai_temperature if temperature is None else temperature,
            timeout=settings.openai_timeout if timeout is None else timeout,
            api_key=settings.openai_api_key if api_key is None else api_key,
            base_url=settings.openai_base_url if base_url is None else base_url,
        )

    async def analyze(
        self,
        system_prompt: str,
        human_prompt: str,
        inputs: dict[str, Any],
    ) -> SentimentResult:
        """分析单条新闻。

        Args:
            system_prompt: 系统提示词（含 JSON 示例，须用 {{ }} 转义花括号）
            human_prompt:  用户提示词模板，含 {title}/{summary} 等占位符
            inputs:        实际填充变量，如 {"title":..., "summary":..., ...}

        Returns:
            SentimentResult；失败时返回降级的中性结果（confidence=0，
            key_sentence 记录失败原因）。
        """
        prompt = ChatPromptTemplate.from_messages([
            ("system", system_prompt),
            ("human", human_prompt),
        ])
        # 主路径：json_mode 结构化输出（比 function calling 兼容性更好）
        structured_chain = prompt | self.llm.with_structured_output(
            SentimentResult, method="json_mode"
        )
        # 兜底路径：普通文本链，自行解析 JSON
        text_chain = prompt | self.llm

        last_err: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                try:
                    return await structured_chain.ainvoke(inputs)
                except Exception as exc:  # 结构化输出失败（不支持/返回非法）→ 落到手动解析
                    last_err = exc
                raw = await text_chain.ainvoke(inputs)
                text = raw.content if isinstance(raw, AIMessage) else str(raw)
                return self._parse_sentiment(text)
            except Exception as exc:  # 网络/超时/鉴权/解析全部失败
                last_err = exc
                if attempt < self.max_retries:
                    wait = self.retry_backoff_s * (2 ** attempt)
                    logger.warning(
                        "LLM 调用失败（第 %d/%d 次），%.1fs 后重试：%s",
                        attempt + 1, self.max_retries + 1, wait, exc,
                    )
                    await asyncio.sleep(wait)
                else:
                    logger.error("LLM 调用最终失败，降级为中性：%s", exc)

        return self._degrade(
            f"LLM 分析失败(重试{self.max_retries}次): {last_err}"
        )

    # ---------------- 解析与降级 ----------------

    @staticmethod
    def _extract_json(text: str):
        """从模型文本中抽取第一个 JSON 对象，兼容 ```json 代码围栏与夹杂文本。"""
        if not text:
            return None
        cleaned = re.sub(r"```(?:json)?", "", text).strip()
        try:
            return json.loads(cleaned)
        except Exception:
            pass
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if not m:
            return None
        try:
            return json.loads(m.group(0))
        except Exception:
            return None

    @classmethod
    def _parse_sentiment(cls, text: str) -> SentimentResult:
        """手动解析兜底：容忍缺失/非法字段，强制范围裁剪，按分值推断标签。"""
        data = cls._extract_json(text)
        if not isinstance(data, dict):
            return cls._degrade("模型返回无法解析为 JSON")

        try:
            score = float(data.get("sentiment_score", 0.0))
        except (TypeError, ValueError):
            score = 0.0
        score = max(-1.0, min(1.0, score))

        try:
            conf = float(data.get("confidence", 0.5))
        except (TypeError, ValueError):
            conf = 0.5
        conf = max(0.0, min(1.0, conf))

        label = data.get("sentiment_label")
        if label not in ("positive", "negative", "neutral"):
            if score > _POS_THRESHOLD:
                label = "positive"
            elif score < _NEG_THRESHOLD:
                label = "negative"
            else:
                label = "neutral"

        topic = str(data.get("topic") or "Other")
        key = data.get("key_sentence")
        key = str(key) if key else None

        return SentimentResult(
            sentiment_score=score,
            sentiment_label=label,
            topic=topic,
            confidence=conf,
            key_sentence=key,
        )

    @staticmethod
    def _degrade(reason: str) -> SentimentResult:
        """最终降级：中性、置信度 0，并记录失败原因到 key_sentence 便于排查。"""
        return SentimentResult(
            sentiment_score=0.0,
            sentiment_label="neutral",
            topic="Other",
            confidence=0.0,
            key_sentence=reason,
        )
