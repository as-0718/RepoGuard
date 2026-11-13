<#
.SYNOPSIS
  注册 RepoGuard 每日巡检计划任务（需以管理员身份运行 PowerShell）。
.DESCRIPTION
  创建两个任务：RepoGuard-HealthSnapshot（02:00）与 RepoGuard-ReadmeSnapshot（02:05）。
  支持 -DryRun（别名 -WhatIf）预览，不实际注册；支持 -ProjectRoot/-RepoRoot 覆盖默认路径。
  仅注册调度，不执行扫描；扫描由既有 CLI 完成。
  原子落盘：--output *.json.tmp，成功后 move /Y 替换为正式 JSON。

  日期格式假设：cmd.exe 的 %DATE% 依赖系统区域格式，本脚本假设 YYYY-MM-DD 前缀。
  若 %DATE:~0,4%%DATE:~5,2%%DATE:~8,2% 解析异常，替代方案：
    1) 在动作中改用 PowerShell 生成日期（Get-Date -Format yyyyMMdd）；
    2) 或先把目标机区域格式统一为 YYYY-MM-DD 再注册。
#>
[CmdletBinding(SupportsShouldProcess = $true)]
param(
  [string]$ProjectRoot = "C:\RepoGuard",
  [string]$RepoRoot = "C:\RepoGuard\demo-repo",
  [switch]$DryRun
)

$ErrorActionPreference = "Stop"
$isDryRun = $DryRun -or $WhatIfPreference

$backend = Join-Path $ProjectRoot "backend"
$python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$logs = Join-Path $ProjectRoot "artifacts\logs"
$healthOut = Join-Path $ProjectRoot "artifacts\health"
$readmeOut = Join-Path $ProjectRoot "artifacts\readme"

if (-not (Test-Path $python)) {
  Write-Error "未找到解释器：$python（请先创建 .venv 并安装依赖）"
  exit 1
}

foreach ($path in @($logs, $healthOut, $readmeOut)) {
  if ($isDryRun) {
    Write-Host "[DRYRUN] New-Item -ItemType Directory -Force $path"
  } else {
    New-Item -ItemType Directory -Force -Path $path | Out-Null
    Write-Host "[PASS] 目录就绪：$path"
  }
}

$dayExpr = "%DATE:~0,4%%DATE:~5,2%%DATE:~8,2%"
$tasks = @(
  @{ Name = "RepoGuard-HealthSnapshot"; Module = "app.health.cli"; At = "02:00"; OutDir = $healthOut; Prefix = "health" },
  @{ Name = "RepoGuard-ReadmeSnapshot"; Module = "app.readme.cli"; At = "02:05"; OutDir = $readmeOut; Prefix = "readme" }
)

foreach ($task in $tasks) {
  # cmd.exe 负责日期展开与日志重定向；先写 .tmp，成功后 move /Y 原子替换
  $inner = "set day=$dayExpr & `"$python`" -m $($task.Module) --repo `"$RepoRoot`" --format json --output `"$($task.OutDir)\$($task.Prefix)-%day%.json.tmp`" >> `"$logs\%day%.log`" 2>&1 && move /Y `"$($task.OutDir)\$($task.Prefix)-%day%.json.tmp`" `"$($task.OutDir)\$($task.Prefix)-%day%.json`""

  $action = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c $inner" -WorkingDirectory $backend
  $trigger = New-ScheduledTaskTrigger -Daily -At $task.At
  $settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -StartWhenAvailable `
                -ExecutionTimeLimit (New-TimeSpan -Minutes 15) -AllowStartIfOnBatteries `
                -DontStopIfGoingOnBatteries
  $principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited

  if ($isDryRun) {
    Write-Host "[DRYRUN] Register-ScheduledTask -TaskName $($task.Name) -Trigger $($task.At) -MultipleInstances IgnoreNew -ExecutionTimeLimit 15m -RunLevel Limited"
    continue
  }

  if ($PSCmdlet.ShouldProcess($task.Name, "注册计划任务")) {
    Register-ScheduledTask -TaskName $task.Name -Action $action -Trigger $trigger -Settings $settings `
      -Principal $principal -Description "RepoGuard 每日巡检（只读）" -Force | Out-Null
    Write-Host "[PASS] 已注册 $($task.Name)（每日 $($task.At)）"
  }
}

Write-Host "[INFO] 未执行扫描；未验证任务真实触发；日志目录：$logs"
Write-Host "[INFO] 未真实注册（-DryRun/-WhatIf 时为预览）；正式注册需管理员权限。"