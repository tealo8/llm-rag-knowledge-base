#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_PID=""
FRONTEND_PID=""

step() {
  printf '\033[36m[知域] %s\033[0m\n' "$1"
}

fail() {
  printf '\033[31m[知域] 启动失败：%s\033[0m\n' "$1" >&2
  exit 1
}

stop_tree() {
  local pid="${1:-}"
  local child
  [[ -z "$pid" ]] && return 0
  if command -v pgrep >/dev/null 2>&1; then
    for child in $(pgrep -P "$pid" 2>/dev/null || true); do
      stop_tree "$child"
    done
  fi
  kill -TERM "$pid" 2>/dev/null || true
}

cleanup() {
  trap - EXIT INT TERM HUP
  [[ -n "$FRONTEND_PID" ]] && step "正在停止前端进程..."
  stop_tree "$FRONTEND_PID"
  [[ -n "$BACKEND_PID" ]] && step "正在停止后端进程..."
  stop_tree "$BACKEND_PID"
  wait "$FRONTEND_PID" 2>/dev/null || true
  wait "$BACKEND_PID" 2>/dev/null || true
}

trap cleanup EXIT
trap 'exit 130' INT TERM HUP

cd "$PROJECT_ROOT"
step "项目目录：$PROJECT_ROOT"

if [[ ! -f .env ]]; then
  [[ -f .env.example ]] || fail "未找到 .env 和 .env.example，无法启动。"
  printf '\033[33m[知域] 未找到 .env，正在从 .env.example 创建。请按需修改模型和密钥配置。\033[0m\n'
  cp .env.example .env
fi

PYTHON_BIN=""
for candidate in python3 python; do
  if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
    PYTHON_BIN="$(command -v "$candidate")"
    break
  fi
done
[[ -n "$PYTHON_BIN" ]] || fail "未检测到 Python 3.10 或更高版本。请安装后重新运行。"
step "Python $($PYTHON_BIN -c 'import platform; print(platform.python_version())') 检测通过。"

command -v node >/dev/null 2>&1 || fail "未检测到 Node.js。请安装 Node.js 20.19+ 或 22.12+ 后重新运行。"
command -v npm >/dev/null 2>&1 || fail "未检测到 npm。请重新安装完整的 Node.js。"
node -e "const [a,b]=process.versions.node.split('.').map(Number); process.exit((a===20&&b>=19)||(a===22&&b>=12)||a>22?0:1)" \
  || fail "当前 Node.js 版本过低。Vite 需要 Node.js 20.19+ 或 22.12+。"
step "Node.js $(node --version) 检测通过。"

port_available() {
  "$PYTHON_BIN" - "$1" <<'PY'
import socket
import sys

sock = socket.socket()
try:
    sock.bind(("127.0.0.1", int(sys.argv[1])))
except OSError:
    raise SystemExit(1)
finally:
    sock.close()
PY
}

for port in 8080 5173; do
  port_available "$port" || fail "端口 $port 已被占用。请关闭占用该端口的程序后重试。"
done

if [[ ! -x venv/bin/python ]]; then
  step "未找到 ./venv，正在创建虚拟环境..."
  "$PYTHON_BIN" -m venv venv || fail "创建 Python 虚拟环境失败。"
fi
VENV_PYTHON="$PROJECT_ROOT/venv/bin/python"

[[ -f backend/requirements.txt ]] || fail "未找到 backend/requirements.txt。"
step "正在安装/校验后端依赖..."
"$VENV_PYTHON" -m pip install --disable-pip-version-check -r backend/requirements.txt \
  || fail "后端依赖安装失败，请检查网络、Python 版本和 requirements.txt。"

[[ -f frontend/package.json ]] || fail "未找到 frontend/package.json。"
if [[ ! -x frontend/node_modules/.bin/vite ]]; then
  step "正在安装前端依赖..."
  (cd frontend && npm ci --no-audit --no-fund) \
    || fail "前端依赖安装失败，请检查网络和 Node.js 版本。"
fi

step "正在构建由 8080 端口托管的前端资源..."
(cd frontend && npm run build) || fail "前端构建失败，请检查 TypeScript/Vite 输出。"

step "正在启动 FastAPI 后端：http://localhost:8080"
(
  cd backend
  exec "$VENV_PYTHON" -m uvicorn app.main:app --host 127.0.0.1 --port 8080
) &
BACKEND_PID=$!

backend_ready=0
for ((attempt = 1; attempt <= 90; attempt++)); do
  kill -0 "$BACKEND_PID" 2>/dev/null || fail "FastAPI 后端启动失败，请检查控制台日志。"
  if "$VENV_PYTHON" -c 'import urllib.request; raise SystemExit(0 if urllib.request.urlopen("http://127.0.0.1:8080/api/health", timeout=2).status == 200 else 1)' 2>/dev/null; then
    backend_ready=1
    break
  fi
  sleep 1
done
[[ "$backend_ready" -eq 1 ]] || fail "FastAPI 后端 90 秒内未就绪，请检查 .env、Ollama 和控制台日志。"

step "后端已就绪，正在启动前端开发服务器：http://localhost:5173"
(
  cd frontend
  VITE_API_URL="http://127.0.0.1:8080/api" exec npm run dev -- --host 127.0.0.1
) &
FRONTEND_PID=$!

frontend_ready=0
for ((attempt = 1; attempt <= 30; attempt++)); do
  kill -0 "$FRONTEND_PID" 2>/dev/null || fail "前端开发服务器启动失败，请检查控制台日志。"
  if ! port_available 5173; then
    frontend_ready=1
    break
  fi
  sleep 1
done
[[ "$frontend_ready" -eq 1 ]] || fail "前端开发服务器 30 秒内未就绪。"

printf '\n\033[32m============================================================\033[0m\n'
printf '\033[32m  知域企业知识库启动成功\033[0m\n'
printf '  应用地址：http://localhost:8080\n'
printf '  开发前端：http://localhost:5173\n'
printf '  API 文档：http://localhost:8080/docs\n'
printf '  管理员：admin / admin123\n'
printf '  普通成员：engineer / engineer123\n'
printf '  只读成员：finance / finance123\n'
printf '\033[33m  按 Ctrl+C 或关闭本启动终端，可停止前后端进程。\033[0m\n'
printf '\033[32m============================================================\033[0m\n\n'

if command -v open >/dev/null 2>&1; then
  open "http://localhost:8080" >/dev/null 2>&1 || true
elif command -v xdg-open >/dev/null 2>&1; then
  xdg-open "http://localhost:8080" >/dev/null 2>&1 || true
else
  printf '\033[33m[知域] 未找到浏览器打开命令，请手动访问 http://localhost:8080\033[0m\n'
fi

while kill -0 "$BACKEND_PID" 2>/dev/null && kill -0 "$FRONTEND_PID" 2>/dev/null; do
  sleep 1
done

if ! kill -0 "$BACKEND_PID" 2>/dev/null; then
  fail "FastAPI 后端已意外退出。"
fi
fail "前端开发服务器已退出。"
