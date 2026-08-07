"""APScheduler 调度器：周期性采集数据 + 生成信号 + 实时爬取新闻。

新闻实时爬取说明（本次优化新增）：
- 通过子进程调用 news_scraper_llm 独立 venv 的 `python -m news_scraper_llm`
  （抓取 Fed/WhiteHouse/AP/CNN 四站点 + qwen-turbo 情感分析），写入与 app 共享的
  data/gold_predictor.db，并回填 news 表内联情感列，使前端无需改造即可看到真实情感。
- 采用子进程方式而非跨包 import，是为了复用 news_scraper_llm 已验证可用的 venv
  （含 Playwright + LangChain + SQLAlchemy），避免污染 app 进程依赖。
"""
from __future__ import annotations

import logging
import atexit
import os
import subprocess
from datetime import datetime, timedelta
from typing import Optional

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.config import PROJECT_ROOT, settings
from app.core.title_summary import summarize_title
from app.models.database import SessionLocal
from app.models.database import Signal
from sqlalchemy import select, func

logger = logging.getLogger(__name__)

_scheduler: Optional[BackgroundScheduler] = None

# news_scraper_llm 独立 venv 的 Python 解释器（爬取任务的执行环境）
_NEWS_SCRAPER_VENV_PYTHON = PROJECT_ROOT / "news_scraper_llm" / ".venv" / "bin" / "python"


def _job_collect():
    """采集因子 + 价格。"""
    from app.core.collectors.base import collect_all_factors, collect_gold_price

    db = SessionLocal()
    try:
        summary = collect_all_factors(db)
        collect_gold_price(db)
        logger.info("采集任务完成: %s", summary)
    except Exception as e:  # noqa: BLE001
        logger.warning("采集任务异常: %s", e)
    finally:
        db.close()


def _job_signal():
    """生成信号。"""
    from app.core.signal_generator import generate_signal

    db = SessionLocal()
    try:
        generate_signal(db)
    except Exception as e:  # noqa: BLE001
        logger.warning("信号生成任务异常: %s", e)
    finally:
        db.close()


def _job_news():
    """采集新闻并分析情感。"""
    from app.core.collectors.adapters import NewsCollector
    from app.core.sentiment import analyze_news
    from app.models.database import News
    from datetime import datetime, timezone

    if not settings.has_newsapi:
        return
    db = SessionLocal()
    try:
        collector = NewsCollector()
        articles = collector.fetch_latest(page_size=10)
        added = 0
        for a in articles:
            url = a.get("url", "")
            if not url:
                continue
            exists = db.execute(
                select(News).where(News.url == url).limit(1)
            ).scalars().first()
            if exists:
                continue
            sent = analyze_news(a.get("title", ""), a.get("content", ""))
            pub = a.get("published_at", "")
            try:
                pub_dt = datetime.fromisoformat(pub.replace("Z", "+00:00"))
            except (ValueError, TypeError):
                pub_dt = datetime.now(timezone.utc)
            db.add(News(
                title=a.get("title", ""),
                title_zh=sent.title_zh or summarize_title(a.get("title", ""), a.get("content", ""), sent.sentiment, sent.topic),
                content=a.get("content", ""),
                source=a.get("source", ""),
                url=url,
                published_at=pub_dt,
                sentiment=sent.sentiment,
                sentiment_label=sent.sentiment_label,
                sentiment_score=sent.sentiment_score,
                topic=sent.topic,
                confidence=sent.confidence,
                key_sentence=sent.key_sentence,
                is_important=sent.is_important,
                hawk_dove=sent.hawk_dove,
                hawk_dove_score=sent.hawk_dove_score,
            ))
            added += 1
        db.commit()
        if added:
            logger.info("新闻采集完成，新增 %d 条", added)
    except Exception as e:  # noqa: BLE001
        db.rollback()
        logger.warning("新闻任务异常: %s", e)
    finally:
        db.close()


def _job_scrape_news() -> None:
    """定时爬取新闻站点 + LLM 情感分析，写入与 app 共享的数据库。

    通过子进程调用 news_scraper_llm 的独立 venv（含 Playwright + LangChain），
    不依赖 NewsAPI 等付费外部接口，因此无论 demo/实时模式都可用，是「实时爬取
    数据源页面内容」的落地实现。任务结果（news 内联情感列 + sentiment 表）会立即
    被前端轮询读取到。
    """
    if not settings.news_scrape_enabled:
        return
    if not _NEWS_SCRAPER_VENV_PYTHON.exists():
        logger.warning(
            "新闻实时爬取跳过：未找到 news_scraper_llm venv（%s）。"
            "请先在其目录内创建 .venv 并安装 playwright/langchain/sqlalchemy。",
            _NEWS_SCRAPER_VENV_PYTHON,
        )
        return

    env = dict(os.environ)
    # 定时任务限制每站点抓取条数，控制 LLM 调用量与单次耗时（手动运行仍用各自 .env 配置）
    env["MAX_ITEMS_PER_SITE"] = str(settings.news_scrape_max_items)
    env["PYTHONUNBUFFERED"] = "1"
    cmd = [str(_NEWS_SCRAPER_VENV_PYTHON), "-m", "news_scraper_llm"]

    logger.info("新闻实时爬取启动：%s", " ".join(cmd))
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(PROJECT_ROOT),
            env=env,
            capture_output=True,
            text=True,
            timeout=600,
        )
        if proc.returncode == 0:
            logger.info("新闻实时爬取完成（耗时由日志给出）")
        else:
            tail = (proc.stderr or proc.stdout or "")[-600:]
            logger.warning("新闻实时爬取异常（rc=%d）：%s", proc.returncode, tail)
    except subprocess.TimeoutExpired:
        logger.warning("新闻实时爬取超时（>600s），已跳过本轮，等待下次触发")
    except Exception as e:  # noqa: BLE001
        logger.warning("新闻实时爬取失败：%s", e)

    # 爬取后把实时情感聚合为规范因子（写入 factor_data，供模型/归因消费）
    try:
        from app.models.database import SessionLocal
        from app.core.sentiment_factor import refresh_sentiment_factor

        with SessionLocal() as db:
            agg = refresh_sentiment_factor(db)
        logger.info(
            "情感因子已同步：value=%.3f count=%d", agg.get("value"), agg.get("count")
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("爬取后情感因子刷新失败（不影响已入库数据）: %s", e)


def start_scheduler() -> None:
    """启动后台调度器。

    说明（本次优化）：
    - 采集/信号任务仅在「非 demo 模式」下挂载（它们依赖外部市场/因子 API）。
    - 新闻实时爬取任务（_job_scrape_news）无论 demo/实时模式都挂载，因为它只依赖
      Playwright + LLM，不依赖任何付费外部接口；并在启动后 15 秒触发一次首爬，
      让页面尽快拿到真实新闻，而非干等一个完整周期。
    """
    global _scheduler
    if _scheduler is not None:
        return
    _scheduler = BackgroundScheduler(timezone="Asia/Shanghai")

    if not settings.demo_mode:
        _scheduler.add_job(
            _job_collect, IntervalTrigger(seconds=settings.collect_interval_seconds),
            id="collect", max_instances=1, coalesce=True,
        )
        _scheduler.add_job(
            _job_signal, IntervalTrigger(seconds=settings.signal_interval_seconds),
            id="signal", max_instances=1, coalesce=True,
        )
        # 原有 NewsAPI 新闻任务（需配置 newsapi_key），与新的爬取任务并存不冲突
        _scheduler.add_job(
            _job_news, IntervalTrigger(seconds=settings.collect_interval_seconds * 2),
            id="news", max_instances=1, coalesce=True,
        )

    if settings.news_scrape_enabled:
        _scheduler.add_job(
            _job_scrape_news,
            IntervalTrigger(seconds=settings.news_scrape_interval_seconds),
            id="news_scrape", max_instances=1, coalesce=True,
        )
        # 启动后 15 秒触发首次爬取，缩短首屏到真实数据的等待
        _scheduler.add_job(
            _job_scrape_news, "date",
            run_date=datetime.now() + timedelta(seconds=15),
            id="news_scrape_initial", max_instances=1, coalesce=True,
        )

    _scheduler.start()
    atexit.register(lambda: _scheduler and _scheduler.shutdown(wait=False))
    logger.info(
        "调度器已启动（采集/信号=%s，新闻爬取=%s，周期=%ds）",
        not settings.demo_mode,
        settings.news_scrape_enabled,
        settings.news_scrape_interval_seconds,
    )


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        logger.info("调度器已停止")
