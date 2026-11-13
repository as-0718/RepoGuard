<#
.SYNOPSIS
  RepoGuard 部署预检（只读）。Linux 等价实现见 deploy/preflight.sh。
.DESCRIPTION
  输出 [PASS]/[WARN]/[SKIP]/[FAIL]；存在 FAIL 时退出码 1，否则 0。
  本脚本不安装、不修改系统、不杀进程，也不执行 docker build / nginx -t。
#>
[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$script:FailCount = 0
$root = Split-Path -Parent $PSScriptRoot

function Write-Pass { param([string]$Message) Write-Host "[PASS] $Message" }
function Write-Warn { param([string]$Item, [string]$Message) Write-Host "[WARN] $Item：$Message" }
function Write-Skip { param([string]$Item, [string]$Message) Write-Host "[SKIP] $Item：$Message" }
function Write-Fail {
  param([string]$Item, [string]$Message)
  Write-Host "[FAIL] $Item：$Message"
  $script:FailCount += 1
}

function Test-VersionAtLeast {
  param([string]$Actual, [string]$Required)
  try {
    return ([version]$Actual) -ge ([version]$Required)
  } catch {
    return $false
  }
}

# ---------- Python ----------
$python = $null
foreach ($candidate in @((Join-Path $root ".venv\Scripts\python.exe"), (Join-Path $root ".venv\bin\python"))) {
  if (Test-Path $candidate) { $python = $candidate; break }
}
if (-not $python) {
  $cmd = Get-Command python -ErrorAction SilentlyContinue
  if ($cmd) { $python = $cmd.Source }
}

if (-not $python) {
  Write-Fail "Python 可用性" "未找到 python 或 .venv 解释器"
} else {
  $pyVersion = & $python -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null
  if (-not $pyVersion) {
    Write-Fail "Python 可用性" "解释器无法执行：$python"
  } elseif (Test-VersionAtLeast $pyVersion "3.10") {
    Write-Pass "Python $pyVersion >= 3.10"
  } else {
    Write-Fail "Python 版本" "当前 $pyVersion，要求 >= 3.10"
  }
}

# ---------- Node / npm（仅构建机需要）----------
$node = Get-Command node -ErrorAction SilentlyContinue
if ($node) {
  $nodeVersion = (& node -v) -replace '^v', ''
  if (Test-VersionAtLeast $nodeVersion "22.12") {
    Write-Pass "Node $nodeVersion >= 22.12"
  } else {
    Write-Fail "Node 版本" "当前 $nodeVersion，要求 >= 22.12（仅构建机）"
  }
} else {
  Write-Skip "Node" "未安装（仅前端构建机需要）"
}

if (Get-Command npm -ErrorAction SilentlyContinue) { Write-Pass "npm 可用" } else { Write-Skip "npm" "未安装（仅前端构建机需要）" }

# ---------- Docker / nginx ----------
if (Get-Command docker -ErrorAction SilentlyContinue) { Write-Pass "docker 可用" } else { Write-Skip "docker" "未安装（不执行真实构建）" }
if (Get-Command nginx -ErrorAction SilentlyContinue) { Write-Pass "nginx 可用" } else { Write-Skip "nginx" "未安装（不执行 nginx -t）" }

# ---------- 必需文件 ----------
if (Test-Path (Join-Path $root "frontend\package-lock.json")) { Write-Pass "frontend/package-lock.json 存在" } else { Write-Fail "依赖锁定" "缺少 frontend/package-lock.json" }
if (Test-Path (Join-Path $root "backend\requirements.txt")) { Write-Pass "backend/requirements.txt 存在" } else { Write-Fail "后端依赖" "缺少 backend/requirements.txt" }

# ---------- .env 忽略状态 ----------
$envFile = Join-Path $root "deploy\.env"
if (Test-Path $envFile) {
  if ((Test-Path (Join-Path $root ".git")) -and (Get-Command git -ErrorAction SilentlyContinue)) {
    & git -C $root check-ignore -q "deploy/.env"
    if ($LASTEXITCODE -eq 0) { Write-Pass "deploy/.env 已被忽略" } else { Write-Warn "deploy/.env" "存在但未被忽略，存在泄露风险" }
  } else {
    Write-Skip "deploy/.env 忽略检查" "当前目录不是 Git 仓库"
  }
} else {
  Write-Warn "deploy/.env" "未创建（上线前从 env.example 复制）"
}

# ---------- 敏感值扫描（不回显原文）----------
$envExample = Join-Path $root "deploy\env.example"
if (Test-Path $envExample) {
  $pattern = 'sk-[A-Za-z0-9]{16,}|AKIA[0-9A-Z]{16}|-----BEGIN'
  if (Select-String -Path $envExample -Pattern $pattern -Quiet) {
    Write-Fail "敏感值扫描" "env.example 命中疑似密钥模式"
  } else {
    Write-Pass "敏感值扫描（env.example）"
  }
} else {
  Write-Fail "敏感值扫描" "缺少 deploy/env.example"
}

# ---------- 端口占用（只读）----------
$busy = @()
foreach ($port in @(8000, 8010, 80, 443, 5173)) {
  $listening = Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue
  if ($listening) { $busy += $port }
}
if ($busy.Count -gt 0) {
  Write-Warn "端口占用" ("已占用：" + ($busy -join ", "))
} else {
  Write-Pass "端口 8000/8010/80/443/5173 未占用"
}

# ---------- 产物目录 ----------
$artifacts = Join-Path $root "artifacts"
if (Test-Path $artifacts -PathType Container) {
  Write-Pass "artifacts 目录存在"
} elseif (Test-Path $root -PathType Container) {
  Write-Pass "项目根存在（上线时创建 artifacts）"
} else {
  Write-Fail "产物目录" "项目根不存在：$root"
}

Write-Host ""
Write-Host ("汇总：FAIL={0}；SKIP/WARN 不计入通过项。" -f $script:FailCount)
Write-Host "[INFO] 未执行 docker build、未执行 nginx -t、未上云。"
if ($script:FailCount -eq 0) { exit 0 } else { exit 1 }