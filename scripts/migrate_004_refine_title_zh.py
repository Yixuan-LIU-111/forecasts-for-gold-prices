"""回填 / 重算 news.title_zh：

将原先「把多空方向（利好黄金/利空黄金）直接作为标题」的反模式，
改为「以关键句内容为核心、呼应重点的中文概括标题」。

幂等规则：
- 仅对【英文标题】的行重算 title_zh（这些才是规则自动生成的、含方向后缀的标题）；
- 【中文标题】的行（手工 demo 种子，如“SPDR黄金ETF持仓量增加2.5吨，创近一个月新高”）
  保持不变，避免被规则产物覆盖。
- 已不含方向后缀的中文标题不会被重复改写。

运行：python scripts/migrate_004_refine_title_zh.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.title_summary import _is_chinese, summarize_title
from app.models.database import News, SessionLocal


def main() -> None:
    db = SessionLocal()
    try:
        rows = db.query(News).all()
        total = len(rows)
        zh_titles = sum(1 for r in rows if _is_chinese(r.title or ""))
        updated = 0
        for n in rows:
            if _is_chinese(n.title or ""):
                # 手工中文标题：保持原样
                continue
            new_zh = summarize_title(
                n.title or "",
                n.key_sentence or "",
                n.sentiment or "",
                n.topic or "",
            )
            old_zh = n.title_zh or ""
            if new_zh and new_zh != old_zh:
                n.title_zh = new_zh
                updated += 1
        db.commit()
        print(
            f"news.title_zh 优化完成：共 {total} 行，"
            f"中文标题 {zh_titles} 行保持不变，重算 {updated} 行（英文标题）。"
        )
    finally:
        db.close()


if __name__ == "__main__":
    main()
