<#
.SYNOPSIS
  注销 RepoGuard 计划任务（幂等；任务不存在时输出 SKIP）。
.DESCRIPTION
  支持 -DryRun（别名 -WhatIf）预览，不实际注销。
  可选清理：-CleanupArtifacts -OlderThanDays 30（默认关闭）。
  -DryRun 只列出将删除的文件，不删除 artifacts 目录本身。
  本脚本不新增默认文件、不执行扫描。
#>
[CmdletBinding(SupportsShouldProcess = $true)]
param(
  [string]$ProjectRoot = "C:\RepoGuard",
  [switch]$DryRun,
  [switch]$CleanupArtifacts,
  [int]$OlderThanDays = 30
)

$ErrorActionPreference = "Stop"
$isDryRun = $DryRun -or $WhatIfPreference

$names = @("RepoGuard-HealthSnapshot", "RepoGuard-ReadmeSnapshot")
foreach ($name in $names) {
  $task = Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
  if ($null -eq $task) {
    Write-Host "[SKIP] 任务不存在：$name"
    continue
  }
  if ($isDryRun) {
    Write-Host "[DRYRUN] Unregister-ScheduledTask -TaskName $name -Confirm:`$false"
    continue
  }
  if ($PSCmdlet.ShouldProcess($name, "注销计划任务")) {
    Unregister-ScheduledTask -TaskName $name -Confirm:$false
    Write-Host "[PASS] 已注销 $name"
  }
}

if ($CleanupArtifacts) {
  if ($OlderThanDays -lt 1) {
    Write-Host "[FAIL] -OlderThanDays 必须为正整数"
    exit 1
  }
  $artifacts = Join-Path $ProjectRoot "artifacts"
  if (-not (Test-Path $artifacts -PathType Container)) {
    Write-Host "[SKIP] artifacts 不存在：$artifacts"
  } else {
    $threshold = (Get-Date).AddDays(-$OlderThanDays)
    $expired = Get-ChildItem -LiteralPath $artifacts -Recurse -File -ErrorAction SilentlyContinue |
      Where-Object { $_.LastWriteTime -lt $threshold -and $_.Name -notlike "*.tmp" }
    if (-not $expired) {
      Write-Host "[INFO] 无超过 $OlderThanDays 天的产物"
    }
    foreach ($file in $expired) {
      if ($isDryRun) {
        Write-Host "[DRYRUN] 将删除：$($file.FullName)"
      } elseif ($PSCmdlet.ShouldProcess($file.FullName, "删除过期产物")) {
        Remove-Item -LiteralPath $file.FullName -Force
        Write-Host "[PASS] 已删除：$($file.FullName)"
      }
    }
    Write-Host "[INFO] 不删除 artifacts 目录本身"
  }
} else {
  Write-Host "[INFO] 未启用 -CleanupArtifacts（默认不清理历史产物）"
}

Write-Host "[INFO] 未执行扫描；未删除 artifacts 目录；未验证任务真实触发。"