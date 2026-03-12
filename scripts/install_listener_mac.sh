#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "Installing Order Bot dependencies in: $ROOT_DIR"

cd "$ROOT_DIR"
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install --upgrade pip
pip install -r requirements.txt

cd "$ROOT_DIR/listener"
npm install

echo ""
echo "Install complete."
echo "Review UI: $ROOT_DIR/scripts/start_review_ui.sh"
echo "Listener:  $ROOT_DIR/scripts/start_listener.sh \"YOUR GROUP NAME\""
