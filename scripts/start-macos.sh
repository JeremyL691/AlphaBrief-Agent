#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_PY="$PROJECT_ROOT/.venv/bin/python"

cd "$PROJECT_ROOT"

if [ ! -x "$VENV_PY" ]; then
  bash "$PROJECT_ROOT/scripts/setup-macos.sh"
fi

if [ ! -f "$PROJECT_ROOT/.env" ]; then
  cp "$PROJECT_ROOT/.env.example" "$PROJECT_ROOT/.env"
fi

exec "$VENV_PY" -m app.launcher
