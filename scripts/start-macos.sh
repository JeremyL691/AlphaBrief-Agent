#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_PY="$PROJECT_ROOT/.venv/bin/python"

cd "$PROJECT_ROOT"

deps_ok() {
  [ -x "$VENV_PY" ] && "$VENV_PY" -c "import fastapi, streamlit, sqlalchemy, requests" >/dev/null 2>&1
}

if ! deps_ok; then
  bash "$PROJECT_ROOT/scripts/setup-macos.sh"
fi

if [ ! -f "$PROJECT_ROOT/.env" ]; then
  cp "$PROJECT_ROOT/.env.example" "$PROJECT_ROOT/.env"
fi

exec "$VENV_PY" -m app.launcher
