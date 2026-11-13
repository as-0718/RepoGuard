#!/usr/bin/env bash
# RepoGuard 冒烟检查（只读）。Windows 等价实现见 deploy/smoke.ps1。
# 需要本机 API 已运行（127.0.0.1:8000）。任一接口非 200 时退出码非 0。
set -u

BASE="${REPOGUARD_SMOKE_BASE:-http://127.0.0.1:8000}"
REPO="${REPOGUARD_SMOKE_REPO:-demo-repo}"

if ! command -v curl >/dev/null 2>&1; then
  printf '[SKIP] curl 不可用，未执行冒烟检查\n'
  printf '[INFO] 未执行上云；未验证真实 HTTPS 证书\n'
  exit 0
fi

TMP_BODY="$(mktemp 2>/dev/null || echo "${TMPDIR:-/tmp}/rg_smoke_body")"
FAIL=0

check() {
  local name="$1"
  local url="$2"
  local code
  code="$(curl -s -o "$TMP_BODY" -w '%{http_code}' --max-time 20 "$url" 2>/dev/null)" || code="000"
  case "$code" in
    200)
      printf '[PASS] %s（%s）\n' "$name" "$code"
      ;;
    000)
      printf '[FAIL] %s：连接失败\n' "$name"
      FAIL=1
      ;;
    503)
      printf '[FAIL] %s：服务降级（%s）\n' "$name" "$code"
      FAIL=1
      ;;
    *)
      printf '[FAIL] %s（%s）\n' "$name" "$code"
      FAIL=1
      ;;
  esac
}

check "健康接口" "$BASE/api/health"
check "仓库清单" "$BASE/api/dashboard/repos"
check "总览快照" "$BASE/api/dashboard/overview?repo=$REPO"

rm -f "$TMP_BODY"
printf '[INFO] 未执行上云；未验证真实 HTTPS 证书\n'
[ "$FAIL" -eq 0 ] && exit 0 || exit 1