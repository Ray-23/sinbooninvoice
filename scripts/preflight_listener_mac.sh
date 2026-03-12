#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET_GROUP_NAME="${1:-${TARGET_GROUP_NAME:-}}"

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

[[ -n "$TARGET_GROUP_NAME" ]] || fail "target group name is missing. Usage: ./scripts/start_listener.sh \"YOUR GROUP NAME\""

for dir in \
  "$ROOT_DIR/data" \
  "$ROOT_DIR/data/incoming" \
  "$ROOT_DIR/data/approved" \
  "$ROOT_DIR/data/rejected" \
  "$ROOT_DIR/data/logs" \
  "$ROOT_DIR/data/mappings" \
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
echo "Target group: $TARGET_GROUP_NAME"
echo "Incoming files: $ROOT_DIR/data/incoming"
echo "Session/auth files: $ROOT_DIR/listener/auth_info_baileys"
