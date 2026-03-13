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

"$ROOT_DIR/scripts/preflight_listener_mac.sh" "$ORDER_GROUP_NAME" "$PRICE_GROUP_NAME"

cd "$ROOT_DIR/listener"
echo ""
echo "Starting WhatsApp listener"
echo "Order group: $ORDER_GROUP_NAME"
echo "Price group: $PRICE_GROUP_NAME"
ORDER_GROUP_NAME="$ORDER_GROUP_NAME" \
PRICE_GROUP_NAME="$PRICE_GROUP_NAME" \
TARGET_GROUP_NAME="$ORDER_GROUP_NAME" \
npm start
