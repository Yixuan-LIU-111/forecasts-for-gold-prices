"""统一日志配置 —— 同时输出到控制台与 artifacts 日志文件。

所有子模块通过 `from .logging_setup import get_logger` 获取 logger，
保证日志格式、落盘位置一致，便于联调与排查。
"""

from __future__ import annotations

import logging
import sys

from . import config

_LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

_configured = False


def get_logger(name: str = "thirty_min") -> logging.Logger:
    """返回统一配置的 logger。

    仅首次调用时，把 handler 安装到父 logger `thirty_min` 上；其余子 logger
    （thirty_min.data / run / automl / eval 等）通过 propagate 复用同一套
    控制台 + 文件输出，避免「只有首个 logger 有输出」的静默 bug。
    """
    global _configured
    root = logging.getLogger("thirty_min")
    if not _configured:
        root.setLevel(logging.INFO)
        formatter = logging.Formatter(_LOG_FORMAT, _DATE_FORMAT)

        # 控制台
        ch = logging.StreamHandler(sys.stdout)
        ch.setFormatter(formatter)
        root.addHandler(ch)

        # 文件
        try:
            fh = logging.FileHandler(
                str(config.LOGS_DIR / "thirty_min.log"), encoding="utf-8"
            )
            fh.setFormatter(formatter)
            root.addHandler(fh)
        except Exception:  # pragma: no cover - 日志文件不可用时不影响主流程
            pass

        root.propagate = False
        _configured = True

    return logging.getLogger(name)
