"""迁移 003：为 news 表添加中文概括标题 title_zh，并回填历史数据。

背景：用户希望前端新闻标题采用“中文概括标题”而非英文原文，提升浏览效率。
本脚本同时修正：
  1) app/dashboard/demo_data/news.json 种子文件（缺 title_zh 时补入）；
  2) 数据库 news 表已写入的历史记录（按 title 生成或复用中文标题）。

幂等：可重复执行；只处理 title_zh 为空或缺失的记录。
执行：python scripts/migrate_003_add_title_zh.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

SEED_JSON = ROOT / "app" / "dashboard" / "demo_data" / "news.json"


def fix_seed_json() -> int:
    """为演示种子文件补入 title_zh（与 title 一致即可，演示数据已是中文）。"""
    if not SEED_JSON.exists():
        print(f"跳过：{SEED_JSON} 不存在")
        return 0
    items = json.loads(SEED_JSON.read_text(encoding="utf-8"))
    changed = 0
    for it in items:
        if not it.get("title_zh"):
            it["title_zh"] = it.get("title", "")
            changed += 1
    if changed:
        SEED_JSON.write_text(
            json.dumps(items, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    print(f"种子文件：补入 {changed} 条 title_zh -> {SEED_JSON.name}")
    return changed


def _ensure_column() -> None:
    """为 news 表添加 title_zh 列（如不存在）。兼容 SQLite / PostgreSQL。"""
    from sqlalchemy import text
    from sqlalchemy.exc import OperationalError, ProgrammingError
    from app.models.database import engine

    with engine.connect() as conn:
        try:
            conn.execute(text("ALTER TABLE news ADD COLUMN title_zh TEXT"))
            conn.commit()
            print("数据库：news.title_zh 列已添加")
        except (OperationalError, ProgrammingError):
            # SQLite 报 duplicate column；PostgreSQL 报 duplicate column
            print("数据库：news.title_zh 列已存在，跳过 ADD COLUMN")


def backfill_db() -> int:
    """为 news 表中 title_zh 为空的记录生成中文概括标题。"""
    import re
    from sqlalchemy import select
    from app.models.database import News, SessionLocal
    from app.core.title_summary import summarize_title

    db = SessionLocal()
    changed = 0
    try:
        rows = db.execute(select(News).where(
            (News.title_zh.is_(None)) | (News.title_zh == "")
        )).scalars().all()

        for row in rows:
            # 标题本身含汉字则直接复用，避免重复生成
            if re.search(r"[\u4e00-\u9fff]", row.title or ""):
                row.title_zh = (row.title or "").strip()
            else:
                row.title_zh = summarize_title(
                    row.title or "",
                    row.key_sentence or "",
                    row.sentiment or "neutral",
                    row.topic or "",
                )
            changed += 1

        if changed:
            db.commit()
    finally:
        db.close()
    print(f"数据库 news 表：回填 {changed} 条 title_zh")
    return changed


def main() -> int:
    fix_seed_json()
    _ensure_column()
    backfill_db()
    print("迁移 003 完成（幂等，可重复执行）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
