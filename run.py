"""
点时成金 —— Windows 可执行文件统一入口。

打包后的 exe 双击即运行：
1. 确保运行时目录（data/ models/ logs/）存在
2. 启动 FastAPI 后端服务（uvicorn）
3. 自动打开浏览器访问仪表盘
4. 控制台打印访问地址与状态信息

用法：
    python run.py            # 开发/调试
    ./点时成金.exe            # 打包后双击运行
"""
from __future__ import annotations

import os
import sys
import time
import webbrowser
import threading
from pathlib import Path

# 确保项目根在 sys.path（开发环境直接运行 run.py 时需要）
_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from app.frozen import ensure_runtime_dirs, EXE_DIR, IS_FROZEN, DOT_ENV_PATH  # noqa: E402
from app.config import settings  # noqa: E402


APP_NAME = "点时成金 · 黄金价格 30 分钟方向预测系统"
HOST = settings.api_host if settings.api_host not in ("0.0.0.0",) else "127.0.0.1"
PORT = settings.api_port


def _print_banner() -> None:
    bar = "=" * 60
    print(bar)
    print(f"  {APP_NAME}")
    print(bar)
    print(f"  运行模式 : {'打包环境 (PyInstaller)' if IS_FROZEN else '开发环境'}")
    print(f"  演示模式 : {'开启' if settings.demo_mode else '关闭'}")
    print(f"  数据目录 : {EXE_DIR / 'data'}")
    print(f"  模型目录 : {EXE_DIR / 'models'}")
    print(f"  配置文件 : {DOT_ENV_PATH} {'(已存在)' if DOT_ENV_PATH.exists() else '(将使用默认值)'}")
    print(bar)


def _open_browser() -> None:
    """延迟打开浏览器，等服务起来后再访问。"""
    url = f"http://{HOST}:{PORT}/dashboard"
    for _ in range(30):
        try:
            import urllib.request
            urllib.request.urlopen(f"http://{HOST}:{PORT}/health", timeout=1)
            break
        except Exception:  # noqa: BLE001
            time.sleep(1)
    else:
        return
    try:
        webbrowser.open(url)
    except Exception:  # noqa: BLE001
        pass


def main() -> None:
    ensure_runtime_dirs()
    _print_banner()

    # 自动打开浏览器（后台线程，避免阻塞服务启动）
    threading.Thread(target=_open_browser, daemon=True).start()

    import uvicorn

    print(f"\n  服务已启动，正在打开仪表盘：http://{HOST}:{PORT}/dashboard\n")
    print("  （按 Ctrl+C 停止服务）\n")

    try:
        uvicorn.run(
            "app.main:app",
            host=HOST,
            port=PORT,
            log_level="info" if not settings.debug else "debug",
            reload=False,
        )
    except KeyboardInterrupt:
        print("\n  服务已停止。")
        sys.exit(0)


if __name__ == "__main__":
    main()
