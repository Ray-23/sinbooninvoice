#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
python3 "$ROOT/scripts/ingest_message.py" --stdin --source sample --group-name "Demo Group" --sender "Demo Sender" < "$ROOT/scripts/sample_order.txt"
