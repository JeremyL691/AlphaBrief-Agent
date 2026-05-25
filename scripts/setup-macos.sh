#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="$PROJECT_ROOT/.venv"
VENV_PY="$VENV_DIR/bin/python"

step() { printf "\n==> %s\n" "$1"; }
die() { printf "\nERROR: %s\n\n" "$1" >&2; exit 1; }

find_python() {
  for candidate in python3.11 python3 /opt/homebrew/bin/python3.11 /usr/local/bin/python3.11; do
    if command -v "$candidate" >/dev/null 2>&1; then
      if "$candidate" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; then
        echo "$candidate"
        return 0
      fi
    fi
  done
  return 1
}

cd "$PROJECT_ROOT"

step "Checking Python"
if ! PYTHON="$(find_python)"; then
  cat >&2 <<'EOF'

ERROR: Python 3.11+ was not found on this Mac.

To install it, pick one option:

  Option A — Homebrew (recommended):
      /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
      brew install python@3.11

  Option B — Official installer:
      https://www.python.org/downloads/macos/  (3.11.x or newer)

After installing, double-click Install-AlphaBrief.command again.
EOF
  exit 1
fi
echo "Using Python: $PYTHON"

if [ ! -x "$VENV_PY" ]; then
  step "Creating virtual environment"
  "$PYTHON" -m venv "$VENV_DIR"
fi

step "Installing Python dependencies"
"$VENV_PY" -m pip install --upgrade pip
"$VENV_PY" -m pip install -e ".[dev]"

if [ ! -f "$PROJECT_ROOT/.env" ]; then
  step "Creating .env from template"
  cp "$PROJECT_ROOT/.env.example" "$PROJECT_ROOT/.env"
fi

echo ""
echo "AlphaBrief Agent setup completed."
echo "Next step: double-click Start-AlphaBrief.command"
