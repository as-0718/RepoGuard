#!/usr/bin/env bash
# RepoGuard one-click installer (Linux / macOS)
# Usage: bash readme/install.sh
# This script only installs dependencies; it does not run the test suite.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_DIR="$REPO_ROOT/backend"
FRONTEND_DIR="$REPO_ROOT/frontend"

echo "==> RepoGuard installer"
echo "Repo root: $REPO_ROOT"

# 1. Backend virtual environment and Python dependencies
if ! command -v python3 >/dev/null 2>&1; then
  echo "Python >= 3.10 (python3) was not found on PATH. Install Python first." >&2
  exit 1
fi

VENV_DIR="$BACKEND_DIR/.venv"
if [ ! -d "$VENV_DIR" ]; then
  echo "==> Creating backend virtual environment..."
  python3 -m venv "$VENV_DIR"
fi

"$VENV_DIR/bin/python" -m pip install --upgrade pip
"$VENV_DIR/bin/python" -m pip install -r "$BACKEND_DIR/requirements.txt"

# 2. Frontend dependencies (optional; Node is only needed for the dashboard)
if command -v node >/dev/null 2>&1; then
  echo "==> Installing frontend dependencies..."
  (cd "$FRONTEND_DIR" && npm ci)
else
  echo "WARN: Node.js >= 22.12 not found; skipped frontend install. Install Node to run the dashboard." >&2
fi

echo "==> Done. Next steps:"
echo "  Backend API : cd backend && .venv/bin/python -m uvicorn app.api.app:app --host 127.0.0.1 --port 8000"
echo "  Frontend    : cd frontend && npm run dev"
echo "  Tests       : cd backend && .venv/bin/python -m unittest discover -s tests -t ."
echo "  Desktop     : Release 便携包解压即用，无需安装 Python / Node 依赖"
