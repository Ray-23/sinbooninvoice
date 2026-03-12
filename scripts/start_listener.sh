#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$ROOT_DIR/.env"

if [[ -f "$ENV_FILE" ]]; then
  set -a
  source "$ENV_FILE"
  set +a
fi

TARGET_GROUP_NAME="${1:-${TARGET_GROUP_NAME:-}}"

"$ROOT_DIR/scripts/preflight_listener_mac.sh" "$TARGET_GROUP_NAME"

cd "$ROOT_DIR/listener"
echo ""
echo "Starting WhatsApp listener for group: $TARGET_GROUP_NAME"
TARGET_GROUP_NAME="$TARGET_GROUP_NAME" npm start
