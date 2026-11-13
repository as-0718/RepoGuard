<#
.SYNOPSIS
  RepoGuard 一键部署编排（默认 dry-run）。Linux 等价实现见 deploy/deploy.sh。
.DESCRIPTION
  默认只打印将执行的命令；传入 -Execute 才实际执行。
  工具缺失项记为 SKIP，不伪报 PASS；失败返回非零退出码。
#>
[CmdletBinding(SupportsShouldProcess = $true)]
param(
  [switch]$DryRun,
  [switch]$Execute
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$isDryRun = -not $Execute

Write-Host ("RepoGuard 部署编排（{0}）" -f $(if ($isDryRun) { "dry-run" } else { "execute" }))

function Invoke-Step {
  param([string]$Description, [scriptblock]$Action)
  if ($isDryRun) {
    Write-Host "[DRYRUN] $Description"
    return
  }
  Write-Host "[RUN] $Description"
  & $Action
}

# 1. 预检（只读，dry-run 也执行）
Write-Host "[STEP] 1/9 预检"
& (Join-Path $PSScriptRoot "preflight.ps1")
if ($LASTEXITCODE -ne 0) {
  Write-Host "[FAIL] 预检存在 FAIL，终止部署"
  exit 1
}
Write-Host "[PASS] 预检通过"

# 2. 后端依赖
Write-Host "[STEP] 2/9 后端依赖"
$python = Join-Path $root ".venv\Scripts\python.exe"
if (Test-Path $python) {
  Invoke-Step "安装后端依赖" { & $python -m pip install -r (Join-Path $root "backend\requirements.txt") }
} else {
  Write-Host "[SKIP] 后端依赖：未找到 .venv 解释器"
}

# 3. 前端构建
Write-Host "[STEP] 3/9 前端构建"
if ($isDryRun) {
  Write-Host ("[DRYRUN] 前端构建：cd {0}\frontend; npm ci; npm run build" -f $root)
} elseif (Get-Command npm -ErrorAction SilentlyContinue) {
  Push-Location (Join-Path $root "frontend")
  try {
    & npm ci
    if ($LASTEXITCODE -ne 0) { Write-Host "[FAIL] npm ci 失败，保留旧 dist"; exit 1 }
    & npm run build
    if ($LASTEXITCODE -ne 0) { Write-Host "[FAIL] npm run build 失败，保留旧 dist"; exit 1 }
  } finally {
    Pop-Location
  }
} else {
  Write-Host "[SKIP] 前端构建：npm 不可用"
}

# 4. 静态投放
Write-Host "[STEP] 4/9 静态投放"
$staticDir = Join-Path $root "frontend\dist"
if (Test-Path $staticDir) {
  Invoke-Step ("投放 dist 到 {0}" -f $staticDir) { Write-Host "[INFO] 目标静态目录由部署环境决定" }
} else {
  Write-Host "[SKIP] 静态投放：dist 不存在"
}

# 5. 服务托管
Write-Host "[STEP] 5/9 服务托管"
if (Get-Command systemctl -ErrorAction SilentlyContinue) {
  Invoke-Step "systemctl enable --now repoguard-api repoguard-webhook" { & systemctl enable --now repoguard-api repoguard-webhook }
} else {
  Write-Host "[SKIP] 服务托管：systemd 不可用"
}

# 6. nginx 校验
Write-Host "[STEP] 6/9 nginx 校验"
if (Get-Command nginx -ErrorAction SilentlyContinue) {
  if ($isDryRun) {
    Write-Host "[DRYRUN] nginx -t"
  } else {
    & nginx -t
    if ($LASTEXITCODE -ne 0) { Write-Host "[FAIL] nginx 配置校验失败"; exit 1 }
    Write-Host "[PASS] nginx 配置校验通过"
  }
} else {
  Write-Host "[SKIP] nginx 校验：未安装 nginx"
}

# 7. 冒烟
Write-Host "[STEP] 7/9 冒烟"
if ($isDryRun) {
  Write-Host "[DRYRUN] powershell -File deploy/smoke.ps1"
} else {
  & (Join-Path $PSScriptRoot "smoke.ps1")
  if ($LASTEXITCODE -ne 0) { Write-Host "[FAIL] 冒烟失败"; exit 1 }
}

# 8. 保留清理（先列后删）
Write-Host "[STEP] 8/9 30 天保留清理"
$artifacts = Join-Path $root "artifacts"
if (Test-Path $artifacts -PathType Container) {
  $threshold = (Get-Date).AddDays(-30)
  $expired = Get-ChildItem -Path $artifacts -Recurse -File -ErrorAction SilentlyContinue |
    Where-Object { $_.LastWriteTime -lt $threshold -and $_.Name -notlike "*.tmp" }
  foreach ($item in $expired) {
    if ($isDryRun) {
      Write-Host ("[DRYRUN] 将删除：{0}" -f $item.FullName)
    } else {
      Remove-Item -LiteralPath $item.FullName -Force
      Write-Host ("[PASS] 已删除：{0}" -f $item.FullName)
    }
  }
  if (-not $expired) { Write-Host "[INFO] 无超过 30 天的产物" }
} else {
  Write-Host "[SKIP] 保留清理：artifacts 不存在"
}

# 9. 汇总
Write-Host "[STEP] 9/9 汇总"
Write-Host "[INFO] 未执行 docker build、未执行 docker compose config、未执行 nginx -t（仅当本机有 nginx 时校验）。"
Write-Host "[INFO] 未执行 hcloud；未上云；未验证真实 HTTPS 证书。"
Write-Host ("部署编排结束（{0}）。" -f $(if ($isDryRun) { "dry-run" } else { "execute" }))
exit 0