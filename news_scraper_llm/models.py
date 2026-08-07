"""
Pydantic 模型：输入 / 输出 / 中间结构
"""
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class RawNewsItem(BaseModel):
    """抓取后、分析前的新闻条目"""

    source: str = Field(..., description="来源站点，如 federal_reserve")
    title: str = Field(..., min_length=1, description="新闻标题")
    url: str | None = Field(default=None, description="原文链接")
    published_at: str | None = Field(default=None, description="发布时间（原始字符串）")
    summary: str | None = Field(default=None, description="正文摘要")
    category: str | None = Field(default=None, description="栏目/分类，如 Press Release / Briefings")
    scraped_at: datetime = Field(default_factory=datetime.utcnow)


class SentimentResult(BaseModel):
    """LLM 情感分析输出（结构化）"""

    sentiment_score: float = Field(
        ..., ge=-1.0, le=1.0,
        description="情感分值，-1 强烈负向，+1 强烈正向"
    )
    sentiment_label: Literal["positive", "negative", "neutral"] = Field(
        ..., description="离散情感标签"
    )
    topic: str = Field(default="Other", description="主题标签")
    confidence: float = Field(..., ge=0.0, le=1.0, description="置信度 0~1")
    key_sentence: str | None = Field(default=None, description="支撑判断的关键句")

    @field_validator("sentiment_score")
    @classmethod
    def round_score(cls, v: float) -> float:
        return round(v, 3)

    @field_validator("confidence")
    @classmethod
    def round_confidence(cls, v: float) -> float:
        return round(v, 2)


class AnalyzedNewsItem(RawNewsItem):
    """抓取 + 情感分析后的完整结果"""

    sentiment_score: float
    sentiment_label: str
    topic: str
    confidence: float
    key_sentence: str | None = None
    sentiment_mode: str = "general"   # 记录分析时使用的模式，便于映射中文标签
    analyzed_at: datetime = Field(default_factory=datetime.utcnow)

    def to_dashboard_dict(self) -> dict:
        """转换为「点时成金」仪表盘 news_list 组件期望的字段格式"""
        is_gold = self.sentiment_mode == "gold"
        return {
            "title": self.title,
            "url": self.url,
            "source": self.source,
            "published_at": self.published_at,
            "sentiment": self.sentiment_label,
            "sentiment_label": {
                "positive": "利多" if is_gold else "正向",
                "negative": "利空" if is_gold else "负向",
                "neutral": "中性",
            }.get(self.sentiment_label, "中性"),
            "sentiment_score": self.sentiment_score,
            "confidence": self.confidence,
            "topic": self.topic,
            "key_sentence": self.key_sentence,
            "category": self.category,
        }
