"""数据库初始化与种子数据引导。

首次启动时从 app/dashboard/demo_data/*.json 导入数据，保证后端开箱即用：
- market_data：从 market.json 的 prices 序列导入
- factor_data：从 factors.json 导入 6 因子
- news：从 news.json 导入
- signals：从 signals.json 导入
- backtest_results：从 backtest.json 导入
- hawk_dove_events：从 backtest.json 的 hawk_dove_events 导入

后续爬虫/LLM/模型生成真实数据后逐步覆盖。
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, date, timezone
from pathlib import Path
from typing import Optional

from sqlalchemy import select, func
from sqlalchemy.orm import Session

from app.config import DEMO_DATA_DIR
from app.models.database import (
    Base,
    SessionLocal,
    engine,
    MarketData,
    FactorData,
    News,
    Signal,
    HawkDoveEvent,
    BacktestResult,
    DataSource,
    init_db,
)

logger = logging.getLogger(__name__)


def _load(name: str) -> Optional[dict | list]:
    path = DEMO_DATA_DIR / f"{name}.json"
    if not path.exists():
        logger.warning("种子文件不存在: %s", path)
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _parse_dt(s: str) -> datetime:
    """解析 ISO 字符串（兼容带/不带时区）。"""
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return datetime.now(timezone.utc)


def _to_date(val) -> Optional[date]:
    """把字符串/日期统一转成 date 对象（SQLite Date 列要求）。"""
    if val is None:
        return None
    if isinstance(val, datetime):
        return val.date()
    if isinstance(val, date):
        return val
    if isinstance(val, str):
        try:
            return datetime.strptime(val[:10], "%Y-%m-%d").date()
        except ValueError:
            return None
    return None


def _count(db: Session, model) -> int:
    return db.execute(select(func.count(model.id))).scalar() or 0


def seed_market(db: Session) -> None:
    if _count(db, MarketData) > 0:
        return
    data = _load("market")
    if not data:
        return
    for p in data.get("prices", []):
        db.add(MarketData(
            timestamp=_parse_dt(p["time"]),
            symbol="XAUUSD",
            price=float(p["price"]),
            volume=int(p.get("volume", 0)),
        ))
    db.commit()
    logger.info("种子 market_data 完成: %d 条", len(data.get("prices", [])))


def seed_factors(db: Session) -> None:
    if _count(db, FactorData) > 0:
        return
    data = _load("factors")
    if not data:
        return
    ts = _parse_dt(data.get("timestamp", datetime.now().isoformat()))
    code_map = {"DXY": "DXY", "TIPS": "TIPS10Y", "VIX": "VIX", "GPR": "GPR",
                "sentiment": "sentiment", "hawk_dove": "hawk_dove"}
    for f in data.get("factors", []):
        code = code_map.get(f.get("name"), f.get("name"))
        realtime = f.get("name") not in ("GPR",)
        db.add(FactorData(
            indicator_code=code,
            indicator_name=f.get("label", ""),
            category="衍生",
            timestamp=ts,
            value=float(f.get("value", 0)),
            value_type="收益率" if code == "TIPS10Y" else "原始值",
            change=float(f["change"]) if f.get("change") is not None else None,
            change_pct=f.get("change_pct"),
            source=f.get("source", ""),
            update_frequency="实时" if realtime else "月度",
            realtime_inference=realtime,
            raw_data=f,
        ))
    db.commit()
    logger.info("种子 factor_data 完成: %d 条", len(data.get("factors", [])))


def seed_news(db: Session) -> None:
    if _count(db, News) > 0:
        return
    data = _load("news")
    if not data:
        return
    for n in data:
        db.add(News(
            title=n.get("title", ""),
            title_zh=n.get("title_zh") or n.get("title", ""),
            source=n.get("source", ""),
            url=n.get("url", f"seed://{n.get('id')}"),
            published_at=_parse_dt(n.get("published_at", datetime.now().isoformat())),
            sentiment=n.get("sentiment"),
            sentiment_label=n.get("sentiment_label"),
            sentiment_score=n.get("sentiment_score"),
            topic=n.get("topic"),
            confidence=n.get("confidence"),
            key_sentence=n.get("key_sentence", ""),
            is_important=n.get("is_important", False),
            hawk_dove=n.get("hawk_dove"),
            hawk_dove_score=n.get("hawk_dove_score"),
        ))
    db.commit()
    logger.info("种子 news 完成: %d 条", len(data))


def seed_signals(db: Session) -> None:
    if _count(db, Signal) > 0:
        return
    data = _load("signals")
    if not data:
        return
    for s in data:
        db.add(Signal(
            timestamp=_parse_dt(s.get("timestamp", datetime.now().isoformat())),
            direction=s.get("direction"),
            direction_en=s.get("direction_en"),
            probability=s.get("probability"),
            strength=s.get("strength"),
            position=s.get("position"),
            position_pct=s.get("position_pct"),
            bull_bear_score=s.get("bull_bear_score"),
            confidence=s.get("confidence"),
            confidence_value=s.get("confidence_value"),
            model=s.get("model", "LightGBM+XGBoost 加权"),
            attribution=s.get("attribution"),
            stop_loss=s.get("stop_loss"),
            take_profit=s.get("take_profit"),
        ))
    db.commit()
    logger.info("种子 signals 完成: %d 条", len(data))


# 真实数据源注册（对应项目内各爬虫：dxy_scraper→新浪、fred_scraper→FRED DFII10、
# vix_scraper→CBOE、gpr_scraper→GPR、news_scraper_llm→NewsAPI/GNews、epu_scraper→EPU）
DATA_SOURCES = [
    ("XAUUSD", "XAU/USD 行情", "新浪财经", "https://finance.sina.com.cn/money/gold/",
     "实时", True, "分钟级价格，回测与信号的主行情源（演示数据为静态样本）"),
    ("DXY", "美元指数 DXY", "新浪财经", "https://finance.sina.com.cn",
     "实时", True, "代理美元走势，上行利空黄金"),
    ("TIPS", "10Y 实际利率", "FRED (DFII10)", "https://fred.stlouisfed.org/series/DFII10",
     "每日", False, "实际利率上行利空黄金"),
    ("VIX", "恐慌指数 VIX", "CBOE", "https://www.cboe.com/tradable_products/vix/",
     "实时", True, "避险情绪代理，上行利多黄金"),
    ("GPR", "地缘政治风险指数", "Caldara-Iacoviello GPR", "https://www.policyuncertainty.com/gpr.html",
     "月度", False, "地缘冲突代理，上行利多黄金"),
    ("sentiment", "新闻情感", "规则引擎（LLM 降级）", None,
     "实时", True, "未配置 OpenAI Key 时降级为规则引擎；生产接 NewsAPI/GNews"),
    ("news", "黄金相关新闻", "NewsAPI / GNews（生产）", "https://newsapi.org",
     "实时", True, "演示数据为静态样本（Reuters/Bloomberg 风格）"),
    ("hawk_dove", "鹰鸽指数", "美联储官员讲话", None,
     "实时", True, "Fed 官员讲话打分，负=鹰派利空黄金"),
]


def seed_data_sources(db: Session) -> None:
    if _count(db, DataSource) > 0:
        return
    for code, name, src, url, freq, rt, desc in DATA_SOURCES:
        db.add(DataSource(
            indicator_code=code,
            indicator_name=name,
            source_name=src,
            source_url=url,
            update_frequency=freq,
            realtime=rt,
            description=desc,
        ))
    db.commit()
    logger.info("种子 data_sources 完成: %d 条", len(DATA_SOURCES))


def seed_backtest(db: Session) -> None:
    if _count(db, BacktestResult) > 0:
        return
    data = _load("backtest")
    if not data:
        return
    summary = data.get("summary", {})
    db.add(BacktestResult(
        summary=summary,
        accuracy=data.get("accuracy", {}),
        equity_curve=data.get("equity_curve", []),
        trade_details=data.get("trade_details", []),
        pnl_distribution=data.get("pnl_distribution", {}),
        params=summary.get("params", {}),
        start_date=_to_date(summary.get("start_date")),
        end_date=_to_date(summary.get("end_date")),
    ))
    # 鹰鸽事件
    for e in data.get("hawk_dove_events", []):
        try:
            d = datetime.strptime(e.get("date", "2026-07-24"), "%Y-%m-%d").date()
        except ValueError:
            d = date(2026, 7, 24)
        db.add(HawkDoveEvent(
            date=d,
            speaker=e.get("speaker"),
            score=e.get("score"),
            type=e.get("type"),
            label=e.get("label"),
            summary=e.get("summary"),
        ))
    db.commit()
    logger.info("种子 backtest + hawk_dove 完成")


def init_app() -> None:
    """初始化数据库表并引导种子数据（幂等）。"""
    init_db()
    db = SessionLocal()
    try:
        seed_market(db)
        seed_factors(db)
        seed_news(db)
        seed_signals(db)
        seed_backtest(db)
        seed_data_sources(db)
    finally:
        db.close()
    logger.info("应用初始化完成")
