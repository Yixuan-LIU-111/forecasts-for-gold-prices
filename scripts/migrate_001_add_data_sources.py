"""迁移脚本：新增 data_sources 表并播种真实数据源（对应前端“数据源配置”面板）。

特性：
- 幂等：仅创建缺失的表，仅在 data_sources 为空时播种；重复运行安全。
- 与已有 SQLite 数据完全兼容：不改动 market_data / factor_data / news /
  signals / backtest_results / economic_calendar 等任何已有表与种子数据。
- 可直接作为项目升级脚本执行，也可由 init_app() 在启动时自动等价完成
  （app/core/seed.py 的 seed_data_sources 已接入 init_app）。

运行方式：
    PYTHONPATH=<项目根> python scripts/migrate_001_add_data_sources.py
"""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.models.database import init_db, SessionLocal
from app.core.seed import seed_data_sources


def main() -> None:
    # 1) 建表：create_all 仅创建缺失的表，已存在表不受影响
    init_db()
    # 2) 播种：seed_data_sources 内部用 _count>0 守卫，空表才写入
    db = SessionLocal()
    try:
        seed_data_sources(db)
    finally:
        db.close()
    print("migration 001: data_sources 表已就绪并完成播种（如原本为空）")


if __name__ == "__main__":
    main()
