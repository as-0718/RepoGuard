# RepoGuard one-click installer (Windows PowerShell)
# Usage: powershell -ExecutionPolicy Bypass -File readme/install.ps1
# This script only installs dependencies; it does not run the test suite.

$ErrorActionPreference = "Stop"

$RepoRoot   = Split-Path $PSScriptRoot -Parent
$BackendDir = Join-Path $RepoRoot "backend"
$FrontendDir = Join-Path $RepoRoot "frontend"

Write-Host "==> RepoGuard installer"
Write-Host "Repo root: $RepoRoot"

# 1. Backend virtual environment and Python dependencies
if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Write-Error "Python >= 3.10 was not found on PATH. Install Python first."
}

$VenvDir    = Join-Path $BackendDir ".venv"
$VenvPython = Join-Path $VenvDir "Scripts\python.exe"

if (-not (Test-Path $VenvDir)) {
    Write-Host "==> Creating backend virtual environment..."
    python -m venv $VenvDir
}

& $VenvPython -m pip install --upgrade pip
& $VenvPython -m pip install -r (Join-Path $BackendDir "requirements.txt")

# 2. Frontend dependencies (optional; Node is only needed for the dashboard)
if (Get-Command node -ErrorAction SilentlyContinue) {
    Write-Host "==> Installing frontend dependencies..."
    Push-Location $FrontendDir
    try {
        npm ci
    } finally {
        Pop-Location
    }
} else {
    Write-Warning "Node.js >= 22.12 not found; skipped frontend install. Install Node to run the dashboard."
}

Write-Host "==> Done. Next steps:"
Write-Host "  Backend API : cd backend; .\.venv\Scripts\python.exe -m uvicorn app.api.app:app --host 127.0.0.1 --port 8000"
Write-Host "  Frontend    : cd frontend; npm run dev"
Write-Host "  Tests       : cd backend; .\.venv\Scripts\python.exe -m unittest discover -s tests -t ."
Write-Host "  Desktop     : Release 便携包解压即用，无需安装 Python / Node 依赖"
