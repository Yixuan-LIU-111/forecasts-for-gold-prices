#!/usr/bin/env bash
# 启动黄金预测系统后端（同源托管前端）。
#
# 为什么不用 --reload：
#   uvicorn 的 --reload 会用 WatchFiles 递归监视整个项目目录，把 .venv_local/
#   下的 streamlit / langchain / langgraph 等上万个文件也纳入监控，内存与 CPU
#   占用持续攀升，长时间运行会被系统 OOM 杀掉（Killed: 9）。
#   如确需热重载，请显式限定目录：
#     uvicorn app.main:app --reload --reload-dir app --reload-dir frontend
#
# 用法：
#   bash scripts/start_backend.sh          # 前台运行（Ctrl+C 退出）
#   nohup bash scripts/start_backend.sh > /tmp/gold_backend.log 2>&1 &   # 后台常驻
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

# 优先使用托管 venv（已装齐 fastapi / langchain_openai 等依赖），否则回退项目内 venv
PY="/Users/echo/.workbuddy/binaries/python/envs/default/bin/python"
if [ ! -x "$PY" ]; then
  if [ -x "$PROJECT_ROOT/.venv_local/bin/python" ]; then
    PY="$PROJECT_ROOT/.venv_local/bin/python"
  else
    PY="$(command -v python3)"
  fi
fi

HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8000}"

# 若端口被占用，先释放，避免 "Address already in use"
if lsof -ti:"$PORT" >/dev/null 2>&1; then
  echo "[start_backend] 端口 $PORT 已被占用，正在释放…"
  lsof -ti:"$PORT" | xargs kill 2>/dev/null || true
  sleep 2
fi

echo "[start_backend] Python : $PY"
echo "[start_backend] 访问地址: http://$HOST:$PORT/"
exec "$PY" -m uvicorn app.main:app --host "$HOST" --port "$PORT"
