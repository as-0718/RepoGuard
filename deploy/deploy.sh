#!/usr/bin/env bash
# RepoGuard 一键部署编排（默认 dry-run）。Windows 等价实现见 deploy/deploy.ps1。
# 用法：bash deploy/deploy.sh [--dry-run|--execute]
# 默认只打印将执行的命令；--execute 才会写系统。工具缺失项记为 SKIP，不伪报 PASS。
set -u

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
DRY_RUN=1

for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=1 ;;
    --execute) DRY_RUN=0 ;;
    -h|--help) echo "用法：bash deploy/deploy.sh [--dry-run|--execute]"; exit 0 ;;
    *) echo "[FAIL] 未知参数：$arg"; exit 2 ;;
  esac
done

run_step() {
  local desc="$1"
  shift
  if [ "$DRY_RUN" -eq 1 ]; then
    printf '[DRYRUN] %s：%s\n' "$desc" "$*"
    return 0
  fi
  printf '[RUN] %s\n' "$desc"
  "$@"
}

printf 'RepoGuard 部署编排（%s）\n' "$([ "$DRY_RUN" -eq 1 ] && echo dry-run || echo execute)"

# 1. 预检（只读，dry-run 也执行）
printf '[STEP] 1/9 预检\n'
if bash "$SCRIPT_DIR/preflight.sh"; then
  printf '[PASS] 预检通过\n'
else
  printf '[FAIL] 预检存在 FAIL，终止部署\n'
  exit 1
fi

# 2. 后端依赖
printf '[STEP] 2/9 后端依赖\n'
if [ -x "$ROOT_DIR/.venv/bin/python" ]; then
  run_step "安装后端依赖" "$ROOT_DIR/.venv/bin/python" -m pip install -r "$ROOT_DIR/backend/requirements.txt"
else
  printf '[SKIP] 后端依赖：未找到 .venv 解释器\n'
fi

# 3. 前端构建
printf '[STEP] 3/9 前端构建\n'
if [ "$DRY_RUN" -eq 1 ]; then
  printf '[DRYRUN] 前端构建：cd %s/frontend && npm ci && npm run build\n' "$ROOT_DIR"
else
  if command -v npm >/dev/null 2>&1; then
    ( cd "$ROOT_DIR/frontend" && npm ci && npm run build ) || { printf '[FAIL] 前端构建失败，保留旧 dist\n'; exit 1; }
  else
    printf '[SKIP] 前端构建：npm 不可用\n'
  fi
fi

# 4. 静态投放
printf '[STEP] 4/9 静态投放\n'
STATIC_DIR="${REPOGUARD_STATIC_DIR:-/usr/share/nginx/html}"
if command -v rsync >/dev/null 2>&1; then
  run_step "投放 dist 到 $STATIC_DIR" rsync -a --delete "$ROOT_DIR/frontend/dist/" "$STATIC_DIR/"
else
  printf '[SKIP] 静态投放：rsync 不可用\n'
fi

# 5. 服务托管
printf '[STEP] 5/9 服务托管\n'
if command -v systemctl >/dev/null 2>&1; then
  run_step "启用并启动服务" systemctl enable --now repoguard-api repoguard-webhook
else
  printf '[SKIP] 服务托管：systemd 不可用\n'
fi

# 6. nginx 校验与重载
printf '[STEP] 6/9 nginx 校验\n'
if command -v nginx >/dev/null 2>&1; then
  if [ "$DRY_RUN" -eq 1 ]; then
    printf '[DRYRUN] nginx -t && systemctl reload nginx\n'
  elif nginx -t; then
    printf '[PASS] nginx 配置校验通过\n'
    systemctl reload nginx || { printf '[FAIL] nginx 重载失败\n'; exit 1; }
  else
    printf '[FAIL] nginx 配置校验失败\n'
    exit 1
  fi
else
  printf '[SKIP] nginx 校验：未安装 nginx\n'
fi

# 7. 冒烟
printf '[STEP] 7/9 冒烟\n'
if [ "$DRY_RUN" -eq 1 ]; then
  printf '[DRYRUN] bash deploy/smoke.sh\n'
else
  bash "$SCRIPT_DIR/smoke.sh" || { printf '[FAIL] 冒烟失败\n'; exit 1; }
fi

# 8. 保留清理（先列后删）
printf '[STEP] 8/9 30 天保留清理\n'
if [ -d "$ROOT_DIR/artifacts" ]; then
  if [ "$DRY_RUN" -eq 1 ]; then
    printf '[DRYRUN] find artifacts -type f -mtime +30 ! -name "*.tmp" -print\n'
  else
    find "$ROOT_DIR/artifacts" -type f -mtime +30 ! -name "*.tmp" -print
    find "$ROOT_DIR/artifacts" -type f -mtime +30 ! -name "*.tmp" -delete
  fi
else
  printf '[SKIP] 保留清理：artifacts 不存在\n'
fi

# 9. 汇总
printf '[STEP] 9/9 汇总\n'
printf '[INFO] 未执行 docker build、未执行 docker compose config、未执行 nginx -t（仅当本机有 nginx 时校验）。\n'
printf '[INFO] 未执行 hcloud；未上云；未验证真实 HTTPS 证书。\n'
printf '部署编排结束（%s）。\n' "$([ "$DRY_RUN" -eq 1 ] && echo dry-run || echo execute)"
exit 0