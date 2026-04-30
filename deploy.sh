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
XVFB_MODE="${NJU_DDL_USE_XVFB:-auto}"
XVFB_DISPLAY="${NJU_DDL_XVFB_DISPLAY:-:99}"
XVFB_SCREEN="${NJU_DDL_XVFB_SCREEN:-1280x900x24}"
VNC_HOST="${NJU_DDL_VNC_HOST:-127.0.0.1}"
VNC_PORT="${NJU_DDL_VNC_PORT:-5900}"
NOVNC_HOST="${NJU_DDL_NOVNC_HOST:-127.0.0.1}"
NOVNC_PORT="${NJU_DDL_NOVNC_PORT:-6080}"
NOVNC_WEB="${NJU_DDL_NOVNC_WEB:-/usr/share/novnc}"
PID_FILE="${NJU_DDL_PID_FILE:-$LOG_DIR/deploy.pids}"
BACKEND_URL_HOST="$BACKEND_HOST"
FRONTEND_URL_HOST="$FRONTEND_HOST"
NOVNC_URL_HOST="$NOVNC_HOST"
if [ "$BACKEND_URL_HOST" = "0.0.0.0" ]; then
    BACKEND_URL_HOST="127.0.0.1"
fi
if [ "$FRONTEND_URL_HOST" = "0.0.0.0" ]; then
    FRONTEND_URL_HOST="localhost"
fi
if [ "$NOVNC_URL_HOST" = "0.0.0.0" ]; then
    NOVNC_URL_HOST="localhost"
fi

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

say()  { printf "${GREEN}==>${NC} %s\n" "$1"; }
warn() { printf "${YELLOW}==>${NC} %s\n" "$1"; }
die()  { printf "${RED}==>${NC} %s\n" "$1"; exit 1; }

SETUP_ONLY=false
STOP_ONLY=false
USE_XVFB=false

usage() {
    cat <<EOF
用法: ./deploy.sh [--setup-only|--stop]

默认行为：安装依赖、构建前端，并启动后端 ${BACKEND_HOST}:${BACKEND_PORT} 与前端 ${FRONTEND_HOST}:${FRONTEND_PORT}。

选项：
  --setup-only   只安装依赖和构建前端，不启动服务
  --stop         停止上一次由 deploy.sh 启动并记录的本地服务
  -h, --help     显示帮助

常用环境变量：
  NJU_DDL_USE_XVFB=false  禁用 Xvfb/noVNC，改用已有 DISPLAY/WAYLAND_DISPLAY
  NJU_DDL_NOVNC_PORT=6080 noVNC 浏览器访问端口
EOF
}

for arg in "$@"; do
    case "$arg" in
        --setup-only)
            SETUP_ONLY=true
            ;;
        --stop)
            STOP_ONLY=true
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
    if python3 - "$host" "$port" <<'PY'
import socket
import sys

host, port = sys.argv[1], int(sys.argv[2])
sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
try:
    sock.bind((host, port))
finally:
    sock.close()
PY
    then
        return
    fi

    warn "${name}端口 ${host}:${port} 已被占用。"
    if command -v ss >/dev/null 2>&1; then
        ss -ltnp "sport = :$port" || true
    fi
    die "请停止占用进程，或设置对应端口环境变量后重试。"
}

stop_recorded_services() {
    if [ ! -f "$PID_FILE" ]; then
        warn "未找到 PID 文件：$PID_FILE"
        return 0
    fi

    warn "正在停止 PID 文件记录的本地服务..."
    while IFS= read -r pid; do
        if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
            kill "$pid" 2>/dev/null || true
        fi
    done < "$PID_FILE"

    while IFS= read -r pid; do
        if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
            wait "$pid" 2>/dev/null || true
        fi
    done < "$PID_FILE"

    rm -f "$PID_FILE"
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

have_virtual_display_tools() {
    command -v Xvfb >/dev/null 2>&1 &&
    command -v x11vnc >/dev/null 2>&1 &&
    command -v fluxbox >/dev/null 2>&1 &&
    command -v websockify >/dev/null 2>&1 &&
    [ -r "$NOVNC_WEB/vnc.html" ]
}

if [ "$STOP_ONLY" = true ]; then
    stop_recorded_services
    exit 0
fi

wait_for_http() {
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

start_virtual_display() {
    say "启动 Xvfb 虚拟桌面..."
    check_port_free "$VNC_HOST" "$VNC_PORT" "VNC"
    check_port_free "$NOVNC_HOST" "$NOVNC_PORT" "noVNC"

    XVFB_LOG="$LOG_DIR/xvfb.log"
    FLUXBOX_LOG="$LOG_DIR/fluxbox.log"
    X11VNC_LOG="$LOG_DIR/x11vnc.log"
    NOVNC_LOG="$LOG_DIR/novnc.log"
    : > "$XVFB_LOG"
    : > "$FLUXBOX_LOG"
    : > "$X11VNC_LOG"
    : > "$NOVNC_LOG"

    export DISPLAY="$XVFB_DISPLAY"
    unset WAYLAND_DISPLAY
    Xvfb "$DISPLAY" -screen 0 "$XVFB_SCREEN" -ac -nolisten tcp >"$XVFB_LOG" 2>&1 &
    XVFB_PID=$!
    PIDS+=("$XVFB_PID")
    sleep 1
    if ! kill -0 "$XVFB_PID" 2>/dev/null; then
        warn "Xvfb 启动失败。日志：$XVFB_LOG"
        tail -n 80 "$XVFB_LOG" || true
        exit 1
    fi

    fluxbox >"$FLUXBOX_LOG" 2>&1 &
    FLUXBOX_PID=$!
    PIDS+=("$FLUXBOX_PID")

    if [ "$VNC_HOST" = "127.0.0.1" ] || [ "$VNC_HOST" = "localhost" ]; then
        x11vnc -display "$DISPLAY" -localhost -no6 -noipv6 -forever -shared -nopw -rfbport "$VNC_PORT" -rfbportv6 "$VNC_PORT" >"$X11VNC_LOG" 2>&1 &
    else
        x11vnc -display "$DISPLAY" -listen "$VNC_HOST" -no6 -noipv6 -forever -shared -nopw -rfbport "$VNC_PORT" -rfbportv6 "$VNC_PORT" >"$X11VNC_LOG" 2>&1 &
    fi
    X11VNC_PID=$!
    PIDS+=("$X11VNC_PID")

    websockify --web "$NOVNC_WEB" "$NOVNC_HOST:$NOVNC_PORT" "$VNC_HOST:$VNC_PORT" >"$NOVNC_LOG" 2>&1 &
    NOVNC_PID=$!
    PIDS+=("$NOVNC_PID")

    if ! wait_for_http "http://${NOVNC_URL_HOST}:${NOVNC_PORT}/vnc.html" "$NOVNC_PID"; then
        warn "noVNC 启动失败或访问超时。日志：$NOVNC_LOG"
        tail -n 80 "$NOVNC_LOG" || true
        exit 1
    fi
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

case "$XVFB_MODE" in
    auto|true|false|1|0)
        ;;
    *)
        die "NJU_DDL_USE_XVFB 只能是 auto、true、false、1 或 0"
        ;;
esac

if [ "$XVFB_MODE" = "true" ] || [ "$XVFB_MODE" = "1" ]; then
    have_virtual_display_tools || die "NJU_DDL_USE_XVFB=true，但缺少 Xvfb/x11vnc/fluxbox/websockify/noVNC 组件。"
    USE_XVFB=true
    export DISPLAY="$XVFB_DISPLAY"
    export NJU_DDL_PLAYWRIGHT_HEADLESS=false
    warn "已按 NJU_DDL_USE_XVFB=true 强制启用 Xvfb/noVNC。"
elif [ -z "${NJU_DDL_PLAYWRIGHT_HEADLESS:-}" ]; then
    if [ "$XVFB_MODE" != "false" ] && [ "$XVFB_MODE" != "0" ] && have_virtual_display_tools; then
        USE_XVFB=true
        export DISPLAY="$XVFB_DISPLAY"
        export NJU_DDL_PLAYWRIGHT_HEADLESS=false
        warn "检测到 Xvfb/noVNC 组件，默认使用虚拟桌面进行平台手动登录。"
    elif [ -n "${DISPLAY:-}" ] || [ -n "${WAYLAND_DISPLAY:-}" ]; then
        export NJU_DDL_PLAYWRIGHT_HEADLESS=false
        warn "检测到图形环境，本地平台登录将启动可见浏览器。"
    else
        export NJU_DDL_PLAYWRIGHT_HEADLESS=true
        warn "未检测到 DISPLAY/WAYLAND_DISPLAY，也缺少 Xvfb/noVNC 组件；平台手动登录不可用。"
    fi
elif [ "${NJU_DDL_PLAYWRIGHT_HEADLESS}" = "false" ] && [ -z "${DISPLAY:-}" ] && [ -z "${WAYLAND_DISPLAY:-}" ]; then
    if [ "$XVFB_MODE" != "false" ] && [ "$XVFB_MODE" != "0" ] && have_virtual_display_tools; then
        USE_XVFB=true
        export DISPLAY="$XVFB_DISPLAY"
        warn "NJU_DDL_PLAYWRIGHT_HEADLESS=false，将自动启动 Xvfb/noVNC。"
    else
        warn "NJU_DDL_PLAYWRIGHT_HEADLESS=false，但未检测到图形环境或 Xvfb/noVNC 组件；平台登录请求会返回可诊断错误。"
    fi
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
    rm -f "$PID_FILE"
    exit "$exit_code"
}
trap cleanup EXIT
trap 'exit 130' INT TERM

if [ "$USE_XVFB" = true ]; then
    start_virtual_display
fi

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

printf "%s\n" "${PIDS[@]}" > "$PID_FILE"

echo ""
say "启动完成！"
echo ""
echo "  后端：http://${BACKEND_URL_HOST}:${BACKEND_PORT}"
echo "  前端：http://${FRONTEND_URL_HOST}:${FRONTEND_PORT}"
if [ "$USE_XVFB" = true ]; then
    echo "  虚拟桌面：http://${NOVNC_URL_HOST}:${NOVNC_PORT}/vnc.html"
fi
echo "  日志：$LOG_DIR"
echo ""
echo "按 Ctrl-C 停止服务。"

wait -n "${PIDS[@]}" || true
warn "有服务已退出，请查看日志：$LOG_DIR"
exit 1
