#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
BACKEND="$ROOT/nju-ddl-tool/backend"
FRONTEND="$ROOT/nju-ddl-tool/frontend"
BACKEND_HOST="${NJU_DDL_BACKEND_HOST:-127.0.0.1}"
BACKEND_PORT="${NJU_DDL_BACKEND_PORT:-8000}"
FRONTEND_HOST="${NJU_DDL_FRONTEND_HOST:-127.0.0.1}"
FRONTEND_PORT="${NJU_DDL_FRONTEND_PORT:-5173}"
LOG_DIR="${TMPDIR:-/tmp}/nju-ddl-tool"
BACKEND_URL_HOST="$BACKEND_HOST"
FRONTEND_URL_HOST="$FRONTEND_HOST"
if [ "$BACKEND_URL_HOST" = "0.0.0.0" ]; then
    BACKEND_URL_HOST="127.0.0.1"
fi
if [ "$FRONTEND_URL_HOST" = "0.0.0.0" ]; then
    FRONTEND_URL_HOST="localhost"
fi

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

say()  { printf "${GREEN}==>${NC} %s\n" "$1"; }
warn() { printf "${YELLOW}==>${NC} %s\n" "$1"; }
die()  { printf "${RED}==>${NC} %s\n" "$1"; exit 1; }

SETUP_ONLY=false

usage() {
    cat <<EOF
用法: ./deploy.sh [--setup-only]

默认行为：安装依赖、构建前端，并启动后端 ${BACKEND_HOST}:${BACKEND_PORT} 与前端 ${FRONTEND_HOST}:${FRONTEND_PORT}。

选项：
  --setup-only   只安装依赖和构建前端，不启动服务
  -h, --help     显示帮助
EOF
}

for arg in "$@"; do
    case "$arg" in
        --setup-only)
            SETUP_ONLY=true
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            die "未知参数：$arg"
            ;;
    esac
done

check_port_free() {
    local host="$1"
    local port="$2"
    local name="$3"
    python3 - "$host" "$port" <<'PY' || die "${name}端口 ${host}:${port} 已被占用，请停止占用进程或设置对应端口环境变量。"
import socket
import sys

host, port = sys.argv[1], int(sys.argv[2])
sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
try:
    sock.bind((host, port))
finally:
    sock.close()
PY
}

wait_for_backend() {
    local url="$1"
    local pid="$2"
    for _ in $(seq 1 30); do
        if python3 - "$url" <<'PY' >/dev/null 2>&1; then
import json
import sys
import urllib.request

url = sys.argv[1]
with urllib.request.urlopen(url, timeout=1) as response:
    data = json.loads(response.read().decode("utf-8"))
    if data.get("ok") is not True:
        raise SystemExit(1)
PY
            return 0
        fi
        if ! kill -0 "$pid" 2>/dev/null; then
            return 1
        fi
        sleep 1
    done
    return 1
}

wait_for_frontend() {
    local url="$1"
    local pid="$2"
    for _ in $(seq 1 30); do
        if python3 - "$url" <<'PY' >/dev/null 2>&1; then
import sys
import urllib.request

with urllib.request.urlopen(sys.argv[1], timeout=1) as response:
    if response.status >= 500:
        raise SystemExit(1)
PY
            return 0
        fi
        if ! kill -0 "$pid" 2>/dev/null; then
            return 1
        fi
        sleep 1
    done
    return 1
}

# ---- Prerequisites ----
say "检查依赖..."

command -v python3 >/dev/null 2>&1 || die "需要 python3（>=3.11）"
command -v uv      >/dev/null 2>&1 || die "需要 uv（https://docs.astral.sh/uv/getting-started/installation/）"
command -v node    >/dev/null 2>&1 || die "需要 node"
command -v npm     >/dev/null 2>&1 || die "需要 npm"

say "依赖检查通过（python3, uv, node, npm）"

# ---- Backend ----
say "安装后端依赖..."
cd "$BACKEND"
uv sync
uv run playwright install chromium

# ---- Secret ----
if [ -z "${NJU_DDL_SECRET:-}" ]; then
    NJU_DDL_SECRET="$(uv run python -c 'import secrets; print(secrets.token_urlsafe(32))')"
    warn "NJU_DDL_SECRET 未设置，已自动生成。"
    warn "  如需固定密钥，请设置环境变量：export NJU_DDL_SECRET=\"...\""
fi
export NJU_DDL_SECRET

if [ -z "${NJU_DDL_PLAYWRIGHT_HEADLESS:-}" ]; then
    export NJU_DDL_PLAYWRIGHT_HEADLESS=false
    warn "NJU_DDL_PLAYWRIGHT_HEADLESS 未设置，本地启动默认使用可见浏览器。"
fi

# ---- Frontend ----
say "安装前端依赖并构建..."
cd "$FRONTEND"
npm install
npm run build

if [ "$SETUP_ONLY" = true ]; then
    # ---- Summary ----
    echo ""
    say "安装和构建完成！启动方式："
    echo ""
    echo "  后端（开发模式）："
    echo "    cd nju-ddl-tool/backend"
    echo "    export NJU_DDL_SECRET='${NJU_DDL_SECRET}'"
    echo "    uv run uvicorn app.main:app --reload --port ${BACKEND_PORT}"
    echo ""
    echo "  前端："
    echo "    cd nju-ddl-tool/frontend"
    echo "    VITE_API_PROXY_TARGET='http://${BACKEND_URL_HOST}:${BACKEND_PORT}' npm run dev -- --host ${FRONTEND_HOST} --port ${FRONTEND_PORT}"
    echo ""
    echo "  打开：http://localhost:${FRONTEND_PORT}"
    exit 0
fi

# ---- Start services ----
say "启动本地服务..."
check_port_free "$BACKEND_HOST" "$BACKEND_PORT" "后端"
check_port_free "$FRONTEND_HOST" "$FRONTEND_PORT" "前端"

mkdir -p "$LOG_DIR"
BACKEND_LOG="$LOG_DIR/backend.log"
FRONTEND_LOG="$LOG_DIR/frontend.log"
: > "$BACKEND_LOG"
: > "$FRONTEND_LOG"

PIDS=()
cleanup() {
    local exit_code=$?
    trap - EXIT
    if [ "${#PIDS[@]}" -gt 0 ]; then
        warn "正在停止本地服务..."
        for pid in "${PIDS[@]}"; do
            if kill -0 "$pid" 2>/dev/null; then
                kill "$pid" 2>/dev/null || true
            fi
        done
        wait "${PIDS[@]}" 2>/dev/null || true
    fi
    exit "$exit_code"
}
trap cleanup EXIT
trap 'exit 130' INT TERM

cd "$BACKEND"
uv run uvicorn app.main:app --host "$BACKEND_HOST" --port "$BACKEND_PORT" >"$BACKEND_LOG" 2>&1 &
BACKEND_PID=$!
PIDS+=("$BACKEND_PID")

if ! wait_for_backend "http://${BACKEND_URL_HOST}:${BACKEND_PORT}/api/health" "$BACKEND_PID"; then
    warn "后端启动失败或健康检查超时。后端日志：$BACKEND_LOG"
    tail -n 80 "$BACKEND_LOG" || true
    exit 1
fi

cd "$FRONTEND"
export VITE_API_PROXY_TARGET="${VITE_API_PROXY_TARGET:-http://${BACKEND_URL_HOST}:${BACKEND_PORT}}"
npm run dev -- --host "$FRONTEND_HOST" --port "$FRONTEND_PORT" --strictPort >"$FRONTEND_LOG" 2>&1 &
FRONTEND_PID=$!
PIDS+=("$FRONTEND_PID")

if ! wait_for_frontend "http://${FRONTEND_URL_HOST}:${FRONTEND_PORT}" "$FRONTEND_PID"; then
    warn "前端启动失败或访问超时。前端日志：$FRONTEND_LOG"
    tail -n 80 "$FRONTEND_LOG" || true
    exit 1
fi

echo ""
say "启动完成！"
echo ""
echo "  后端：http://${BACKEND_URL_HOST}:${BACKEND_PORT}"
echo "  前端：http://${FRONTEND_URL_HOST}:${FRONTEND_PORT}"
echo "  日志：$LOG_DIR"
echo ""
echo "按 Ctrl-C 停止服务。"

wait -n "${PIDS[@]}" || true
warn "有服务已退出，请查看日志：$LOG_DIR"
exit 1
