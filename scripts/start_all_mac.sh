#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$ROOT_DIR/.env"
UI_URL="http://127.0.0.1:5001"
AUTH_DIR="$ROOT_DIR/listener/auth_info_baileys"
INCOMING_DIR="$ROOT_DIR/data/incoming"
PRICES_CATALOG="$ROOT_DIR/data/prices/latest_prices.json"
VENV_PYTHON="$ROOT_DIR/.venv/bin/python3"
UI_PID=""

if [[ -f "$ENV_FILE" ]]; then
  set -a
  source "$ENV_FILE"
  set +a
fi

ORDER_GROUP_NAME="${ORDER_GROUP_NAME:-${TARGET_GROUP_NAME:-}}"
PRICE_GROUP_NAME="${PRICE_GROUP_NAME:-}"

cleanup() {
  if [[ -n "$UI_PID" ]] && kill -0 "$UI_PID" >/dev/null 2>&1; then
    kill "$UI_PID" >/dev/null 2>&1 || true
    wait "$UI_PID" 2>/dev/null || true
  fi
}

trap cleanup EXIT INT TERM

[[ -x "$VENV_PYTHON" ]] || {
  echo "Missing virtual environment at $ROOT_DIR/.venv" >&2
  echo "Run: $ROOT_DIR/scripts/install_listener_mac.sh" >&2
  exit 1
}

"$ROOT_DIR/scripts/preflight_listener_mac.sh" "$ORDER_GROUP_NAME" "$PRICE_GROUP_NAME"

echo "UI URL: $UI_URL"
echo "Order group name: $ORDER_GROUP_NAME"
echo "Price group name: $PRICE_GROUP_NAME"
echo "Auth folder path: $AUTH_DIR"
echo "Incoming folder path: $INCOMING_DIR"
echo "Prices catalog path: $PRICES_CATALOG"
echo ""
echo "Starting review UI in background..."
"$ROOT_DIR/scripts/start_review_ui.sh" >""$ROOT_DIR/data/logs/review_ui_stdout.log"" 2>&1 &
UI_PID=$!

for _ in {1..30}; do
  if curl -fsS "$UI_URL" >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

if ! curl -fsS "$UI_URL" >/dev/null 2>&1; then
  echo "Review UI did not become reachable at $UI_URL" >&2
  exit 1
fi

echo "Opening Google Chrome to $UI_URL"
if ! open -a "Google Chrome" "$UI_URL"; then
  echo "Google Chrome could not be opened automatically. Opening the default browser instead."
  open "$UI_URL"
fi

echo ""
echo "WhatsApp listener will stay in the foreground so the QR code remains visible."
"$ROOT_DIR/scripts/start_listener.sh" "$ORDER_GROUP_NAME" "$PRICE_GROUP_NAME"
