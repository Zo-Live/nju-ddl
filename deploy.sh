#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
BACKEND="$ROOT/nju-ddl-tool/backend"
FRONTEND="$ROOT/nju-ddl-tool/frontend"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

say()  { printf "${GREEN}==>${NC} %s\n" "$1"; }
warn() { printf "${YELLOW}==>${NC} %s\n" "$1"; }
die()  { printf "${RED}==>${NC} %s\n" "$1"; exit 1; }

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

# ---- Frontend ----
say "安装前端依赖并构建..."
cd "$FRONTEND"
npm install
npm run build

# ---- Summary ----
echo ""
say "部署完成！启动方式："
echo ""
echo "  后端（开发模式）："
echo "    cd nju-ddl-tool/backend"
echo "    export NJU_DDL_SECRET='${NJU_DDL_SECRET}'"
echo "    uv run uvicorn app.main:app --reload --port 8000"
echo ""
echo "  前端（已构建到 dist/，可用任意静态服务器托管）："
echo "    cd nju-ddl-tool/frontend"
echo "    npm run dev    # 开发模式，默认 http://localhost:5173"
echo ""
echo "  或一键启动（后端）："
echo "    cd nju-ddl-tool/backend && NJU_DDL_SECRET='${NJU_DDL_SECRET}' uv run uvicorn app.main:app --host 0.0.0.0 --port 8000"
echo ""
echo "  生产环境请务必："
echo "    - 将 NJU_DDL_SECRET 设为固定长随机字符串"
echo "    - 使用 HTTPS 反向代理（nginx / caddy）"
echo "    - 将前端 dist/ 部署到静态文件服务器"
