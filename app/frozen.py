"""
PyInstaller 冻结环境路径工具。

所有模块统一通过此模块获取路径，不再直接使用 Path(__file__).parent.parent，
确保在开发环境和 PyInstaller 打包后的 exe 环境中路径均正确。

路径约定：
- 开发环境：PROJECT_ROOT = 仓库根目录
- 打包环境：
  - _MEIPASS = PyInstaller 临时解压目录（只读，存放打包进去的代码/资源）
  - _EXE_DIR  = exe 所在目录（可写，存放 data/ models/ .env 等运行时文件）
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def _get_exe_dir() -> Path:
    """exe 所在目录（可写，用于 data/ models/ .env）。

    - 开发环境：仓库根目录
    - 打包环境（onedir）：取 sys.executable 所在目录（dist/<app>/），
      与只读资源同级，适合持久化数据库/模型
    - 打包环境（.app 包）：运行时不应写入包体内（会破坏签名），
      因此落在「.app 所在目录」下（包外），例如 dist/data、dist/models
    """
    if getattr(sys, "frozen", False):
        exe = Path(sys.executable).resolve()
        # macOS .app: .../<名>.app/Contents/MacOS/<名>
        if "Contents/MacOS" in str(exe):
            # 回退四级到 .app 所在目录：MacOS -> Contents -> <名>.app -> 父目录
            return exe.parent.parent.parent.parent
        return exe.parent
    return Path(__file__).resolve().parent.parent


def _get_meipass() -> Path:
    """PyInstaller 临时解压目录（只读，存放打包资源）。

    开发环境返回 None，表示使用正常的项目目录。
    """
    if getattr(sys, "frozen", False):
        mp = getattr(sys, "_MEIPASS", None)
        if mp:
            return Path(mp)
    return None


def _get_project_root() -> Path:
    """项目根目录。

    - 打包环境：_MEIPASS（所有 .py 打包在此）
    - 开发环境：app/config.py 的上两级
    """
    meipass = _get_meipass()
    if meipass is not None:
        return meipass
    return Path(__file__).resolve().parent.parent


# ---- 全局常量 ----
PROJECT_ROOT: Path = _get_project_root()
"""项目根目录（只读）。打包时为 _MEIPASS 解压目录。"""

EXE_DIR: Path = _get_exe_dir()
"""exe 所在目录（可写）。开发环境等同于 PROJECT_ROOT。"""

IS_FROZEN: bool = getattr(sys, "frozen", False)
"""是否在 PyInstaller 打包环境中运行。"""

# 可写目录（exe 同级，首次启动时自动创建）
DATA_DIR: Path = EXE_DIR / "data"
MODELS_DIR: Path = EXE_DIR / "models"
LOGS_DIR: Path = EXE_DIR / "logs"

# 打包时随 exe 预置到 _MEIPASS 的资源（只读），首次运行时拷贝到可写目录
_SEED_DB_SRC: Path | None = (PROJECT_ROOT / "data_seed" / "gold_predictor.db") if IS_FROZEN else None
_MODEL_SRC: Path | None = (PROJECT_ROOT / "models" / "predictor.joblib") if IS_FROZEN else None

# 只读资源（打包进 exe，运行时从 _MEIPASS 读取）
FRONTEND_DIR: Path = PROJECT_ROOT / "frontend"
DEMO_DATA_DIR: Path = PROJECT_ROOT / "app" / "dashboard" / "demo_data"

# 配置文件
DOT_ENV_PATH: Path = EXE_DIR / ".env"


def ensure_runtime_dirs() -> None:
    """确保可写目录存在（exe 首次启动时调用）。

    打包环境下：若可写目录尚未初始化，则从 _MEIPASS 预置资源拷贝基础数据
    （数据库 / 预训练模型），避免首次启动因缺文件而报错或重新训练。
    """
    for d in (DATA_DIR, MODELS_DIR, LOGS_DIR):
        d.mkdir(parents=True, exist_ok=True)

    # 首次运行：拷贝预置数据库（若可写目录中尚不存在）
    if _SEED_DB_SRC is not None and _SEED_DB_SRC.exists():
        dst = DATA_DIR / "gold_predictor.db"
        if not dst.exists():
            try:
                import shutil
                shutil.copy2(_SEED_DB_SRC, dst)
            except Exception:  # noqa: BLE001
                pass

    # 首次运行：拷贝预置模型（若可写目录中尚不存在）
    if _MODEL_SRC is not None and _MODEL_SRC.exists():
        dst = MODELS_DIR / "predictor.joblib"
        if not dst.exists():
            try:
                import shutil
                shutil.copy2(_MODEL_SRC, dst)
            except Exception:  # noqa: BLE001
                pass


def get_frontend_html() -> Path:
    """前端仪表盘 HTML 文件路径。"""
    return FRONTEND_DIR / "dashboard.html"


def get_scraper_root() -> Path:
    """爬虫模块根目录。

    开发环境 = PROJECT_ROOT；打包环境爬虫代码也在 _MEIPASS 中。
    """
    return PROJECT_ROOT
