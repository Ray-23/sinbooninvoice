#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_PYTHON="$ROOT_DIR/.venv/bin/python3"

[[ -x "$VENV_PYTHON" ]] || {
  echo "Missing virtual environment at $ROOT_DIR/.venv" >&2
  echo "Run: $ROOT_DIR/scripts/install_listener_mac.sh" >&2
  exit 1
}

cd "$ROOT_DIR"
echo "Starting review UI at http://127.0.0.1:5001"
exec "$VENV_PYTHON" review_ui/app.py
