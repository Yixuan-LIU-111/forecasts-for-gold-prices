"""LLM 新闻情感 + 鹰鸽立场特征工程（方案文档 §3.3 / §9.2 / §9.3 / §9.4）

职责：
1. 加载新闻条目（来自 news_scraper_llm 输出缓存，字段含 title/summary/published_at，
   以及 LLM 已分析的 sentiment_score；也可接入实时新闻 + LLM）。
2. 为每条新闻抽取两个核心信号（方案文档要求）：
   - sentiment_score ∈ [-1, +1]  黄金利多(+)/利空(-)，由 LLM 或其规则降级给出
   - hawkish_score   ∈ [-1, +1]  鹰派(+1)/鸽派(-1)（文档：鹰派→利空黄金）
3. 将不规则的新闻时间对齐到建模的 bar 时间轴（日频近似 or 真实 30 分钟 bar），
   按 bar 聚合为 sentiment_score / hawkish_score 的水平值 + news_count。
4. 返回与建模底表同维度的情感子表，由 features.attach_sentiment_features
   进一步计算文档 §9.4 的滚动特征（sentiment_mean_30 / sentiment_max_30 / hawkish_change）。

降级策略（对齐文档 US-003 / US-007 异常场景「LLM 超时时降级为规则引擎」）：
- provider="openai" 且配置了密钥 → 调 OpenAI 兼容接口（含 qwen-turbo 等）
- provider="ollama" → 调本地 Ollama（http://localhost:11434）
- provider="rule" 或上述任一失败 → 关键词规则引擎（零依赖、可离线复现）
- 若新闻条目本身已带 LLM 分析的 sentiment_score，rule 模式下优先复用该值（真实 LLM 结果），
  仅用规则补算缺失的 hawkish_score。
"""

from __future__ import annotations

import json
import re
import urllib.request
from pathlib import Path
from typing import Iterable, Sequence

import numpy as np
import pandas as pd

import config as C


# ================================================================== 词典（规则引擎）
# 文档 §9.2 同义词表 + §9.3 鹰鸽语义。仅作离线降级，不替代 LLM。
_HAWKISH_TERMS = [  # → +1（鹰派 / 紧缩）
    "加息", "紧缩", "鹰派", "hawkish", "tighten", "tightening", "rate hike",
    "contractionary", "hiking", "restrictive",
]
_DOVISH_TERMS = [   # → -1（鸽派 / 宽松）
    "降息", "宽松", "鸽派", "dovish", "ease", "easing", "rate cut",
    "expansionary", "quantitative easing", "qe", "accommodative",
]
# 黄金情感（利多 +1 / 利空 -1），依据 §9.2 判断规则
_BULL_GOLD = [  # → +1（利多黄金）
    "降息", "鸽派", "宽松", "dovish", "easing", "rate cut", "qe",
    "地缘", "冲突", "避险", "通胀", "inflation", "tariff", "关税",
    "stimulus", "safe-haven", "safe haven", "量化宽松",
]
_BEAR_GOLD = [  # → -1（利空黄金）
    "加息", "鹰派", "紧缩", "hawkish", "tighten", "rate hike",
    "美元升值", "美元走强", "strong dollar", "抛售", "sell-off", "selloff",
]


def _lexicon_score(text: str | None, pos: Sequence[str], neg: Sequence[str]) -> float:
    """关键词规则打分：命中正负词数之差 / 总数 ∈ [-1, 1]。"""
    if not text:
        return 0.0
    t = str(text).lower()
    p = sum(t.count(w.lower()) for w in pos)
    n = sum(t.count(w.lower()) for w in neg)
    if p + n == 0:
        return 0.0
    return float(p - n) / (p + n)


# ================================================================== 新闻加载
def load_news_items(news_dir: Path = C.NEWS_DIR) -> list[dict]:
    """读取 news_scraper_output 下所有 news_sentiment_*.json，归一化字段。"""
    news_dir = Path(news_dir)
    if not news_dir.exists():
        return []
    items: list[dict] = []
    for f in sorted(news_dir.glob("news_sentiment_*.json")):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        for r in d.get("data", []):
            items.append({
                "title": r.get("title") or "",
                "summary": r.get("summary") or "",
                "source": r.get("source") or "",
                "published_at": r.get("published_at") or r.get("scraped_at") or "",
                # 复用 news_scraper_llm 已分析的 LLM 情感分（若有）
                "cached_sentiment": _to_float(r.get("sentiment_score")),
                "topic": r.get("topic") or "Other",
                "confidence": _to_float(r.get("confidence")),
            })
    return items


def _to_float(v) -> float | None:
    try:
        if v is None:
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def _parse_date(s: str) -> pd.Timestamp | None:
    if not s:
        return None
    for fmt in (None,):
        try:
            dt = pd.to_datetime(s, errors="coerce")
            if pd.notna(dt):
                return dt
        except Exception:
            pass
    return None


# ================================================================== 提取器
class NewsSentimentExtractor:
    """为单条新闻抽取 (sentiment_score, hawkish_score, source_tag)。

    source_tag 记录信号来源（"llm" / "cached" / "rule"），便于复现与审计。
    """

    def __init__(self, provider: str | None = None,
                 api_key: str | None = None,
                 base_url: str | None = None, model: str | None = None):
        self.provider = (provider or C.LLM_PROVIDER or "rule").lower()
        self.api_key = api_key or C.OPENAI_API_KEY or ""
        if not self.api_key:
            self.api_key = (C.OPENAI_API_KEY
                            or __import__("os").environ.get("OPENAI_API_KEY", ""))
        self.base_url = base_url or C.OPENAI_BASE_URL
        self.model = model or C.OPENAI_MODEL
        self._llm_ok = self._probe_llm()

    # ---------------- 公开接口 ----------------
    def extract(self, item: dict) -> dict:
        text = f"{item.get('title','')}. {item.get('summary','')}"
        cached = item.get("cached_sentiment")

        # sentiment_score
        if self.provider != "rule" and self._llm_ok:
            try:
                s = self._llm_call(text)["sentiment_score"]
                s_src = "llm"
            except Exception:
                s = cached if cached is not None else _lexicon_score(text, _BULL_GOLD, _BEAR_GOLD)
                s_src = "cached" if cached is not None else "rule"
        else:
            # rule 模式：优先复用已存在的 LLM 情感分，否则规则打分
            if cached is not None:
                s, s_src = float(cached), "cached"
            else:
                s, s_src = _lexicon_score(text, _BULL_GOLD, _BEAR_GOLD), "rule"

        # hawkish_score（文档无缓存，统一：LLM 或规则）
        if self.provider != "rule" and self._llm_ok:
            try:
                h = self._llm_call(text)["hawkish_score"]
                h_src = "llm"
            except Exception:
                h, h_src = _lexicon_score(text, _HAWKISH_TERMS, _DOVISH_TERMS), "rule"
        else:
            h, h_src = _lexicon_score(text, _HAWKISH_TERMS, _DOVISH_TERMS), "rule"

        return {"sentiment_score": float(np.clip(s, -1, 1)),
                "hawkish_score": float(np.clip(h, -1, 1)),
                "sentiment_source": s_src, "hawkish_source": h_src}

    # ---------------- LLM 路径 ----------------
    def _probe_llm(self) -> bool:
        if self.provider == "openai":
            return bool(self.api_key)
        if self.provider == "ollama":
            try:
                req = urllib.request.Request(f"{C.OLLAMA_BASE_URL.rstrip('/')}/api/tags",
                                             headers={"Content-Type": "application/json"})
                with urllib.request.urlopen(req, timeout=3) as r:
                    return r.status == 200
            except Exception:
                return False
        return False

    def _llm_call(self, text: str) -> dict:
        system = (
            "你是黄金市场政策与新闻分析专家。分析给定文本对黄金价格的影响，"
            "并判断其中的货币政策立场。仅输出 JSON："
            '{"sentiment_score": float, "hawkish_score": float}。'
            "sentiment_score: -1(强烈利空黄金) ~ +1(强烈利多黄金)；"
            "hawkish_score: -1(鸽派/宽松) ~ +1(鹰派/紧缩)。不要输出多余内容。"
        )
        user = f"文本：{text[:1500]}"
        if self.provider == "openai":
            payload = {
                "model": self.model,
                "temperature": 0,
                "messages": [{"role": "system", "content": system},
                             {"role": "user", "content": user}],
                "response_format": {"type": "json_object"},
            }
            req = urllib.request.Request(
                f"{self.base_url.rstrip('/')}/chat/completions",
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json",
                         "Authorization": f"Bearer {self.api_key}"},
                method="POST")
            with urllib.request.urlopen(req, timeout=C.LLM_TIMEOUT) as r:
                data = json.loads(r.read().decode("utf-8"))
            content = data["choices"][0]["message"]["content"]
        else:  # ollama
            payload = {"model": self.model, "prompt": f"{system}\n{user}",
                       "stream": False, "format": "json"}
            req = urllib.request.Request(
                f"{C.OLLAMA_BASE_URL.rstrip('/')}/api/generate",
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(req, timeout=C.LLM_TIMEOUT) as r:
                data = json.loads(r.read().decode("utf-8"))
            content = data.get("response", "")
        return self._parse_llm_json(content)

    @staticmethod
    def _parse_llm_json(content: str) -> dict:
        if not content:
            raise ValueError("空响应")
        cleaned = re.sub(r"```(?:json)?", "", content).strip()
        try:
            d = json.loads(cleaned)
        except Exception:
            m = re.search(r"\{.*\}", cleaned, re.DOTALL)
            if not m:
                raise ValueError("无法解析 JSON")
            d = json.loads(m.group(0))
        s = float(np.clip(_to_float(d.get("sentiment_score")) or 0.0, -1, 1))
        h = float(np.clip(_to_float(d.get("hawkish_score")) or 0.0, -1, 1))
        return {"sentiment_score": s, "hawkish_score": h}


# ================================================================== 特征构建
class NewsSentimentFeatureBuilder:
    """把新闻条目对齐到 bar 时间轴并聚合成情感特征子表。"""

    def __init__(self, provider: str | None = None):
        self.extractor = NewsSentimentExtractor(provider=provider)

    def build(self, news_items: list[dict], bar_dates: pd.Series,
              bar_interval_minutes: int = C.ACTUAL_BAR_INTERVAL_MINUTES
              ) -> tuple[pd.DataFrame, dict]:
        """返回 (情感子表[date, sentiment_score, hawkish_score, news_count], meta)。

        bar_dates: 建模底表的日期序列（升序）。新闻按 asof 对齐到 <= 自身的最后一根 bar。
        """
        meta = {"n_news": len(news_items), "source_breakdown": {},
                "n_bars_with_news": 0, "date_range": None}
        if not news_items:
            meta["note"] = "无新闻数据：情感特征全为中性 0（模型退化为不含情感）"
            empty = pd.DataFrame({"date": pd.to_datetime(bar_dates).values,
                                  "sentiment_score": 0.0, "hawkish_score": 0.0,
                                  "news_count": 0})
            return empty, meta

        # 1) 逐条抽取
        recs = []
        for it in news_items:
            dt = _parse_date(it.get("published_at") or "")
            if dt is None:
                continue
            ex = self.extractor.extract(it)
            recs.append({"date": dt, **ex})
        if not recs:
            meta["note"] = "新闻日期均无法解析：情感特征全为中性 0"
            empty = pd.DataFrame({"date": pd.to_datetime(bar_dates).values,
                                  "sentiment_score": 0.0, "hawkish_score": 0.0,
                                  "news_count": 0})
            return empty, meta

        news_df = pd.DataFrame(recs).sort_values("date").reset_index(drop=True)
        for c in ("sentiment_score", "hawkish_score"):
            news_df[c] = news_df[c].astype(float)
        news_df["news_count"] = 1

        # 来源统计
        meta["source_breakdown"] = {
            "sentiment": dict(news_df["sentiment_source"].value_counts()),
            "hawkish": dict(news_df["hawkish_source"].value_counts()),
        }
        meta["date_range"] = [str(news_df["date"].min().date()),
                              str(news_df["date"].max().date())]

        # 2) asof 对齐到 bar 时间轴（新闻 → 最近的过去 bar）
        bars = pd.DataFrame({"date": pd.to_datetime(bar_dates).values})\
            .sort_values("date").reset_index(drop=True)
        # merge_asof 要求两侧同名列作 key，故把 bar 日期复制一份为 bar_date 随行带出
        bars2 = bars.copy()
        bars2["bar_date"] = bars2["date"]
        merged = pd.merge_asof(
            news_df.sort_values("date"),
            bars2.sort_values("date"),
            on="date", direction="backward")
        merged = merged.dropna(subset=["bar_date"])

        # 3) 按 bar 聚合：均值（情绪/立场） + 计数
        agg = (merged.groupby("bar_date")
                     .agg(sentiment_score=("sentiment_score", "mean"),
                          hawkish_score=("hawkish_score", "mean"),
                          news_count=("news_count", "sum"))
                     .reset_index().rename(columns={"bar_date": "date"}))

        # 4) 对齐到完整 bar 序列（无新闻 bar 填中性 0）
        full = pd.DataFrame({"date": bars["date"].values})
        out = full.merge(agg, on="date", how="left")
        out["sentiment_score"] = out["sentiment_score"].fillna(0.0)
        out["hawkish_score"] = out["hawkish_score"].fillna(0.0)
        out["news_count"] = out["news_count"].fillna(0).astype(int)
        out = out.sort_values("date").reset_index(drop=True)

        meta["n_bars_with_news"] = int((out["news_count"] > 0).sum())
        return out, meta


# ================================================================== 便捷入口
def build_sentiment_features(bar_dates: pd.Series,
                             news_dir: Path = C.NEWS_DIR,
                             provider: str | None = None,
                             bar_interval_minutes: int = C.ACTUAL_BAR_INTERVAL_MINUTES,
                             use_cache: bool = True,
                             cache_path: Path = C.SENTIMENT_CACHE_CSV
                             ) -> tuple[pd.DataFrame, dict]:
    """端到端：加载新闻 → 抽取 → 对齐聚合 → 落盘缓存 → 返回情感子表与 meta。"""
    cache_path = Path(cache_path)
    if use_cache and cache_path.exists():
        df = pd.read_csv(cache_path, parse_dates=["date"])
        # 仅在 bar 序列匹配时复用缓存
        if len(df) == len(bar_dates):
            return df, {"from_cache": True}

    items = load_news_items(news_dir)
    builder = NewsSentimentFeatureBuilder(provider=provider)
    frame, meta = builder.build(items, bar_dates,
                                bar_interval_minutes=bar_interval_minutes)
    frame.to_csv(cache_path, index=False)
    meta["from_cache"] = False
    meta["cached_to"] = str(cache_path)
    return frame, meta


if __name__ == "__main__":
    import data_loader as DL
    base = DL.build_dataset(refresh=False, save=False)
    sf, meta = build_sentiment_features(base["date"], provider="rule")
    print("meta:", json.dumps(meta, ensure_ascii=False, default=str))
    print(sf.tail(8))
