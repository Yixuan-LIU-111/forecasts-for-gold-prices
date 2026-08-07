"""迁移 002：把演示新闻的占位链接（example.com）替换为真实来源站点链接。

背景：docs/前端页面优化.docx 建议 3 要求「新闻标题可点击跳转原文」。
原演示数据 url 全部为 https://example.com/news/N，点击后无意义。
本脚本同时修正：
  1) app/dashboard/demo_data/news.json 中的种子文件；
  2) 数据库 news 表中已写入的历史记录（按 id 匹配）。

幂等：可重复执行；只在 url 缺失或仍为 example.com 占位时才覆盖。
执行：python scripts/migrate_002_fix_news_urls.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

SEED_JSON = ROOT / "app" / "dashboard" / "demo_data" / "news.json"

# 按新闻主题指向对应来源的真实栏目页（演示数据无法给出逐条原文，
# 因此使用来源方的黄金/宏观栏目作为可点击落点，优于 example.com 占位）
URL_BY_ID: dict[str, str] = {
    "n001": "https://www.reuters.com/markets/rates-bonds/",
    "n002": "https://www.bea.gov/data/personal-consumption-expenditures-price-index",
    "n003": "https://apnews.com/hub/middle-east",
    "n004": "https://www.gold.org/goldhub/data/gold-etfs-holdings-and-flows",
    "n005": "https://www.cnbc.com/federal-reserve/",
    "n006": "https://www.reuters.com/markets/commodities/",
    "n007": "https://www.dol.gov/ui/data.pdf",
    "n008": "https://www.kitco.com/price/precious-metals",
    "n009": "https://www.bloomberg.com/quote/DXY:CUR",
    "n010": "https://fred.stlouisfed.org/series/DFII10",
}

PLACEHOLDER = "example.com"


def _needs_fix(url: str | None) -> bool:
    return (not url) or (PLACEHOLDER in url)


def fix_seed_json() -> int:
    if not SEED_JSON.exists():
        print(f"跳过：{SEED_JSON} 不存在")
        return 0
    items = json.loads(SEED_JSON.read_text(encoding="utf-8"))
    changed = 0
    for it in items:
        new_url = URL_BY_ID.get(it.get("id"))
        if new_url and _needs_fix(it.get("url")):
            it["url"] = new_url
            changed += 1
    if changed:
        SEED_JSON.write_text(
            json.dumps(items, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    print(f"种子文件：更新 {changed} 条 url -> {SEED_JSON.name}")
    return changed


def _seed_key(row) -> str | None:
    """把库内记录映射回种子编号 nXXX。

    news 表主键为自增整数，与种子文件的 n001/n002 不同；
    这里优先解析占位 URL 里的序号，其次退化为按主键序号推导。
    """
    import re

    m = re.search(r"/news/(\d+)", str(row.url or ""))
    if m:
        return f"n{int(m.group(1)):03d}"
    try:
        return f"n{int(row.id):03d}"
    except (TypeError, ValueError):
        return None


def fix_db() -> int:
    from sqlalchemy import select

    from app.models.database import News, SessionLocal

    db = SessionLocal()
    changed = 0
    try:
        for row in db.execute(select(News)).scalars().all():
            if not _needs_fix(row.url):
                continue
            key = _seed_key(row)
            new_url = URL_BY_ID.get(key) if key else None
            if new_url:
                row.url = new_url
                changed += 1
        if changed:
            db.commit()
    finally:
        db.close()
    print(f"数据库 news 表：更新 {changed} 条 url")
    return changed


def main() -> int:
    fix_seed_json()
    fix_db()
    print("迁移 002 完成（幂等，可重复执行）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
