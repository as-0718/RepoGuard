<#
.SYNOPSIS
  RepoGuard 冒烟检查（只读）。Linux 等价实现见 deploy/smoke.sh。
.DESCRIPTION
  需要本机 API 已运行（127.0.0.1:8000）。任一接口非 200 时退出码非 0。
#>
[CmdletBinding()]
param(
  [string]$Base = "http://127.0.0.1:8000",
  [string]$Repo = "demo-repo"
)

$ErrorActionPreference = "Stop"
$script:Fail = 0

function Test-Endpoint {
  param([string]$Name, [string]$Url)
  $code = 0
  try {
    $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 20
    $code = [int]$response.StatusCode
  } catch {
    if ($_.Exception.Response) {
      $code = [int]$_.Exception.Response.StatusCode
    } else {
      $code = 0
    }
  }

  if ($code -eq 200) {
    Write-Host ("[PASS] {0}（{1}）" -f $Name, $code)
  } elseif ($code -eq 0) {
    Write-Host ("[FAIL] {0}：连接失败" -f $Name)
    $script:Fail = 1
  } elseif ($code -eq 503) {
    Write-Host ("[FAIL] {0}：服务降级（{1}）" -f $Name, $code)
    $script:Fail = 1
  } else {
    Write-Host ("[FAIL] {0}（{1}）" -f $Name, $code)
    $script:Fail = 1
  }
}

Test-Endpoint "健康接口" ("{0}/api/health" -f $Base)
Test-Endpoint "仓库清单" ("{0}/api/dashboard/repos" -f $Base)
Test-Endpoint "总览快照" ("{0}/api/dashboard/overview?repo={1}" -f $Base, $Repo)

Write-Host "[INFO] 未执行上云；未验证真实 HTTPS 证书"
if ($script:Fail -eq 0) { exit 0 } else { exit 1 }