from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from parser.price_parser import parse_price_message

ROOT = Path(__file__).resolve().parents[1]
SAMPLE_PATH = ROOT / 'scripts' / 'sample_price_message.txt'
OUTPUT_PATH = ROOT / 'data' / 'logs' / 'price_parser_test_output.json'
REQUIRED_ITEMS = {
    'Broccoli': 29.0,
    'Cauliflower': 28.0,
    'Carrot': 14.5,
    'Facai pumkin': 3.2,
}


def main() -> None:
    raw_message = SAMPLE_PATH.read_text(encoding='utf-8')
    received_at = datetime.now().replace(microsecond=0).isoformat()
    result = parse_price_message(raw_message, received_at)

    item_map = {entry['normalized_item']: entry for entry in result['items']}
    for item_name, expected_price in REQUIRED_ITEMS.items():
        entry = item_map.get(item_name)
        if not entry:
            raise SystemExit(f'Missing parsed item: {item_name}')
        if round(float(entry['reference_price']), 2) != expected_price:
            raise SystemExit(f'Unexpected price for {item_name}: {entry["reference_price"]}')

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding='utf-8')
    print(json.dumps(result, indent=2, ensure_ascii=False))
    print(f'\nSaved price parser test output to: {OUTPUT_PATH}')


if __name__ == '__main__':
    main()
