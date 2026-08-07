#!/usr/bin/env bash
# ============================================================
# 「点时成金」测试一键执行脚本
#
# 用法：
#   bash scripts/run_tests.sh              # 完整回归（默认，跳过 external）
#   bash scripts/run_tests.sh smoke        # 冒烟：仅单元 + 接口，秒级
#   bash scripts/run_tests.sh unit         # 只跑单元测试
#   bash scripts/run_tests.sh api          # 只跑接口测试
#   bash scripts/run_tests.sh integration  # 只跑集成测试
#   bash scripts/run_tests.sh e2e          # 只跑端到端测试
#   bash scripts/run_tests.sh perf         # 只跑性能基线
#   bash scripts/run_tests.sh security     # 只跑安全基线
#   bash scripts/run_tests.sh full         # 含 external 的全量（需外网 / Node）
#   bash scripts/run_tests.sh install      # 仅安装测试依赖
#
# 产物（统一输出到 reports/）：
#   reports/pytest-report.html   自包含 HTML 测试报告
#   reports/junit.xml            JUnit XML（供 CI 解析）
#   reports/coverage-html/       覆盖率 HTML 报告（入口 index.html）
#   reports/coverage.xml         Cobertura 覆盖率（供 CI / SonarQube）
#   reports/summary.txt          纯文本结果摘要
# ============================================================
set -uo pipefail

# —— 定位仓库根目录 ——
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${ROOT_DIR}" || exit 1

REPORT_DIR="${ROOT_DIR}/reports"
mkdir -p "${REPORT_DIR}"

# —— 选择 Python 解释器：优先项目 venv ——
if [[ -x "${ROOT_DIR}/.venv/bin/python" ]]; then
  PY="${ROOT_DIR}/.venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  PY="$(command -v python3)"
else
  echo "[错误] 未找到可用的 Python 解释器" >&2
  exit 1
fi

echo "============================================================"
echo " 项目根目录 : ${ROOT_DIR}"
echo " Python     : ${PY} ($("${PY}" --version 2>&1))"
echo " 报告输出   : ${REPORT_DIR}"
echo "============================================================"

# —— 依赖安装（缺失才装，幂等）——
install_deps() {
  echo ">>> 检查并安装测试依赖 ..."
  if ! "${PY}" -c "import pytest, pytest_cov, pytest_html, pytest_timeout" >/dev/null 2>&1; then
    "${PY}" -m pip install -q --upgrade pip
    "${PY}" -m pip install -q -r "${ROOT_DIR}/requirements-test.txt"
    echo ">>> 测试依赖安装完成"
  else
    echo ">>> 测试依赖已就绪，跳过安装"
  fi
}

MODE="${1:-all}"

if [[ "${MODE}" == "install" ]]; then
  install_deps
  exit 0
fi

install_deps

# —— 按模式拼装 pytest 参数 ——
MARK_EXPR=""
EXTRA=""
case "${MODE}" in
  smoke)       MARK_EXPR="(unit or api) and not slow and not external" ;;
  unit)        MARK_EXPR="unit" ;;
  api)         MARK_EXPR="api" ;;
  integration) MARK_EXPR="integration" ;;
  e2e)         MARK_EXPR="e2e and not external" ;;
  perf)        MARK_EXPR="perf" ;;
  security)    MARK_EXPR="security" ;;
  full)        MARK_EXPR="" ;;
  all|"")      MARK_EXPR="not external" ;;
  *)
    echo "[错误] 未知模式：${MODE}" >&2
    echo "可选：all | smoke | unit | api | integration | e2e | perf | security | full | install" >&2
    exit 2
    ;;
esac

PYTEST_ARGS=(
  "tests"
  "-v"
  "--color=yes"
  "--timeout=120"
  "--junitxml=${REPORT_DIR}/junit.xml"
  "--html=${REPORT_DIR}/pytest-report.html"
  "--self-contained-html"
  "--cov=app"
  "--cov-report=term-missing:skip-covered"
  "--cov-report=html:${REPORT_DIR}/coverage-html"
  "--cov-report=xml:${REPORT_DIR}/coverage.xml"
  "--cov-config=${ROOT_DIR}/.coveragerc"
)
if [[ -n "${MARK_EXPR}" ]]; then
  PYTEST_ARGS+=("-m" "${MARK_EXPR}")
fi

echo ""
echo ">>> 执行模式：${MODE}${MARK_EXPR:+  （标记过滤：${MARK_EXPR}）}"
echo ">>> 命令：${PY} -m pytest ${PYTEST_ARGS[*]}"
echo ""

"${PY}" -m pytest "${PYTEST_ARGS[@]}" 2>&1 | tee "${REPORT_DIR}/pytest-output.log"
EXIT_CODE="${PIPESTATUS[0]}"

# —— 生成纯文本摘要（供验收报告直接引用）——
{
  echo "==================== 测试执行摘要 ===================="
  echo "执行时间 : $(date '+%Y-%m-%d %H:%M:%S')"
  echo "执行模式 : ${MODE}"
  echo "Python   : $("${PY}" --version 2>&1)"
  echo "退出码   : ${EXIT_CODE}"
  echo "------------------------------------------------------"
  grep -E "^(FAILED|ERROR)" "${REPORT_DIR}/pytest-output.log" || echo "无失败用例"
  echo "------------------------------------------------------"
  grep -E "passed|failed|error" "${REPORT_DIR}/pytest-output.log" | tail -3
  echo "------------------------------------------------------"
  grep -E "^TOTAL" "${REPORT_DIR}/pytest-output.log" || true
  echo "======================================================"
} > "${REPORT_DIR}/summary.txt"

echo ""
cat "${REPORT_DIR}/summary.txt"
echo ""
echo "报告已生成："
echo "  测试报告   : ${REPORT_DIR}/pytest-report.html"
echo "  覆盖率报告 : ${REPORT_DIR}/coverage-html/index.html"
echo "  JUnit XML  : ${REPORT_DIR}/junit.xml"
echo "  执行摘要   : ${REPORT_DIR}/summary.txt"

exit "${EXIT_CODE}"
