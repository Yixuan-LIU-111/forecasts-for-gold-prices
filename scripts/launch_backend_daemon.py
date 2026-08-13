#!/usr/bin/env python3
"""把 uvicorn 后端以守护进程方式拉起（脱离工具进程组，常驻存活）。"""
import os
import sys

PY = "/Users/echo/.workbuddy/binaries/python/envs/default/bin/python"
CWD = "/Users/echo/Desktop/forecasts for gold prices"


def daemonize_and_run():
    # 第一次 fork，父进程立即退出，让工具调用结束
    if os.fork() > 0:
        os._exit(0)
    # 创建新会话，脱离原进程组/控制终端
    os.setsid()
    # 第二次 fork，确保不是会话首进程，避免重新获取终端
    if os.fork() > 0:
        os._exit(0)
    os.chdir(CWD)
    # 重定向标准流，避免持有工具管道
    devnull = os.open(os.devnull, os.O_RDWR)
    os.dup2(devnull, 0)
    os.dup2(devnull, 1)
    os.dup2(devnull, 2)
    # 执行真正的后端
    os.execv(PY, [PY, "-m", "uvicorn", "app.main:app",
                  "--host", "127.0.0.1", "--port", "8000"])


if __name__ == "__main__":
    daemonize_and_run()
