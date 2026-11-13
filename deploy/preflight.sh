#!/usr/bin/env bash
# RepoGuard 部署预检（只读）。Windows 等价实现见 deploy/preflight.ps1。
# 输出 [PASS]/[WARN]/[SKIP]/[FAIL]；存在 FAIL 时退出码 1，否则 0。
set -u

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
FAIL_COUNT=0

pass() { printf '[PASS] %s\n' "$1"; }
warn() { printf '[WARN] %s：%s\n' "$1" "$2"; }
skip() { printf '[SKIP] %s：%s\n' "$1" "$2"; }
bad()  { printf '[FAIL] %s：%s\n' "$1" "$2"; FAIL_COUNT=$((FAIL_COUNT + 1)); }

version_ge() {
  awk -v a="$1" -v b="$2" 'BEGIN {
    split(a, x, "."); split(b, y, ".");
    for (i = 1; i <= 3; i++) {
      xi = x[i] + 0; yi = y[i] + 0;
      if (xi > yi) exit 0;
      if (xi < yi) exit 1;
    }
    exit 0;
  }'
}

# ---------- Python ----------
PY_BIN=""
if [ -x "$ROOT_DIR/.venv/bin/python" ]; then
  PY_BIN="$ROOT_DIR/.venv/bin/python"
elif [ -x "$ROOT_DIR/.venv/Scripts/python.exe" ]; then
  PY_BIN="$ROOT_DIR/.venv/Scripts/python.exe"
elif command -v python3 >/dev/null 2>&1; then
  PY_BIN="python3"
elif command -v python >/dev/null 2>&1; then
  PY_BIN="python"
fi

if [ -z "$PY_BIN" ]; then
  bad "Python 可用性" "未找到 python3/python 或 .venv 解释器"
else
  PY_VERSION="$("$PY_BIN" -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null || true)"
  if [ -z "$PY_VERSION" ]; then
    bad "Python 可用性" "解释器无法执行：$PY_BIN"
  elif version_ge "$PY_VERSION" "3.10"; then
    pass "Python $PY_VERSION >= 3.10"
  else
    bad "Python 版本" "当前 $PY_VERSION，要求 >= 3.10"
  fi
fi

# ---------- Node / npm（仅构建机需要）----------
if command -v node >/dev/null 2>&1; then
  NODE_VERSION="$(node -v 2>/dev/null | sed 's/^v//')"
  if version_ge "$NODE_VERSION" "22.12"; then
    pass "Node $NODE_VERSION >= 22.12"
  else
    bad "Node 版本" "当前 $NODE_VERSION，要求 >= 22.12（仅构建机）"
  fi
else
  skip "Node" "未安装（仅前端构建机需要）"
fi

if command -v npm >/dev/null 2>&1; then
  pass "npm 可用"
else
  skip "npm" "未安装（仅前端构建机需要）"
fi

# ---------- Docker / nginx ----------
command -v docker >/dev/null 2>&1 && pass "docker 可用" || skip "docker" "未安装（不执行真实构建）"
command -v nginx >/dev/null 2>&1 && pass "nginx 可用" || skip "nginx" "未安装（不执行 nginx -t）"

# ---------- 必需文件 ----------
[ -f "$ROOT_DIR/frontend/package-lock.json" ] && pass "frontend/package-lock.json 存在" || bad "依赖锁定" "缺少 frontend/package-lock.json"
[ -f "$ROOT_DIR/backend/requirements.txt" ] && pass "backend/requirements.txt 存在" || bad "后端依赖" "缺少 backend/requirements.txt"

# ---------- .env 忽略状态 ----------
if [ -f "$ROOT_DIR/deploy/.env" ]; then
  if command -v git >/dev/null 2>&1 && git -C "$ROOT_DIR" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    if git -C "$ROOT_DIR" check-ignore -q deploy/.env; then
      pass "deploy/.env 已被忽略"
    else
      warn "deploy/.env" "存在但未被忽略，存在泄露风险"
    fi
  else
    skip "deploy/.env 忽略检查" "当前目录不是 Git 仓库"
  fi
else
  warn "deploy/.env" "未创建（上线前从 env.example 复制）"
fi

# ---------- 敏感值扫描（不回显原文）----------
if grep -Eq 'sk-[A-Za-z0-9]{16,}|AKIA[0-9A-Z]{16}|-----BEGIN' "$ROOT_DIR/deploy/env.example" 2>/dev/null; then
  bad "敏感值扫描" "env.example 命中疑似密钥模式"
else
  pass "敏感值扫描（env.example）"
fi

# ---------- 端口占用（只读）----------
if command -v ss >/dev/null 2>&1; then
  BUSY=""
  for port in 8000 8010 80 443 5173; do
    if ss -ltn 2>/dev/null | awk '{print $4}' | grep -Eq "[:.]$port$"; then
      BUSY="$BUSY $port"
    fi
  done
  if [ -n "$BUSY" ]; then
    warn "端口占用" "已占用：$BUSY"
  else
    pass "端口 8000/8010/80/443/5173 未占用"
  fi
else
  skip "端口占用检查" "ss 不可用"
fi

# ---------- 产物目录可写 ----------
if [ -d "$ROOT_DIR/artifacts" ]; then
  [ -w "$ROOT_DIR/artifacts" ] && pass "artifacts 可写" || bad "产物目录" "artifacts 不可写"
else
  [ -w "$ROOT_DIR" ] && pass "项目根可写（上线时创建 artifacts）" || bad "产物目录" "项目根不可写"
fi

printf '\n汇总：FAIL=%d；SKIP/WARN 不计入通过项。\n' "$FAIL_COUNT"
printf '[INFO] 未执行 docker build、未执行 nginx -t、未上云。\n'
[ "$FAIL_COUNT" -eq 0 ] && exit 0 || exit 1