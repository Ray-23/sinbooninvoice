#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$ROOT_DIR/.env"

if [[ -f "$ENV_FILE" ]]; then
  set -a
  source "$ENV_FILE"
  set +a
fi

ORDER_GROUP_NAME="${1:-${ORDER_GROUP_NAME:-${TARGET_GROUP_NAME:-}}}"
PRICE_GROUP_NAME="${2:-${PRICE_GROUP_NAME:-}}"

fail() {
  echo "Preflight failed: $1" >&2
  exit 1
}

command -v node >/dev/null 2>&1 || fail "node is not installed"
command -v npm >/dev/null 2>&1 || fail "npm is not installed"
command -v python3 >/dev/null 2>&1 || fail "python3 is not installed"

NODE_VERSION="$(node -v)"
NPM_VERSION="$(npm -v)"
PYTHON_VERSION="$(python3 -V 2>&1)"

[[ -n "$ORDER_GROUP_NAME" ]] || fail "order group name is missing. Set ORDER_GROUP_NAME or TARGET_GROUP_NAME, or run ./scripts/start_listener.sh \"ORDER GROUP\" \"PRICE GROUP\""
[[ -n "$PRICE_GROUP_NAME" ]] || fail "price group name is missing. Set PRICE_GROUP_NAME, or run ./scripts/start_listener.sh \"ORDER GROUP\" \"PRICE GROUP\""

mkdir -p \
  "$ROOT_DIR/data/incoming" \
  "$ROOT_DIR/data/approved" \
  "$ROOT_DIR/data/rejected" \
  "$ROOT_DIR/data/logs" \
  "$ROOT_DIR/data/prices/raw" \
  "$ROOT_DIR/data/prices/history"

for dir in \
  "$ROOT_DIR/data" \
  "$ROOT_DIR/data/incoming" \
  "$ROOT_DIR/data/approved" \
  "$ROOT_DIR/data/rejected" \
  "$ROOT_DIR/data/logs" \
  "$ROOT_DIR/data/mappings" \
  "$ROOT_DIR/data/prices" \
  "$ROOT_DIR/data/prices/raw" \
  "$ROOT_DIR/data/prices/history" \
  "$ROOT_DIR/listener" \
  "$ROOT_DIR/scripts"
do
  [[ -d "$dir" ]] || fail "required folder is missing: $dir"
done

for file in \
  "$ROOT_DIR/data/mappings/customers.json" \
  "$ROOT_DIR/data/mappings/items.json" \
  "$ROOT_DIR/requirements.txt" \
  "$ROOT_DIR/listener/package.json" \
  "$ROOT_DIR/scripts/ingest_message.py"
do
  [[ -f "$file" ]] || fail "required file is missing: $file"
done

echo "Preflight OK"
echo "Node: $NODE_VERSION"
echo "npm: $NPM_VERSION"
echo "Python: $PYTHON_VERSION"
echo "Order group: $ORDER_GROUP_NAME"
echo "Price group: $PRICE_GROUP_NAME"
echo "Incoming files: $ROOT_DIR/data/incoming"
echo "Session/auth files: $ROOT_DIR/listener/auth_info_baileys"
echo "Prices catalog: $ROOT_DIR/data/prices/latest_prices.json"
