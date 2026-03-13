from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from parser.price_parser import apply_reference_prices, find_reference_match, parse_price_message

ROOT = Path(__file__).resolve().parents[1]
SAMPLE_PATH = ROOT / 'scripts' / 'sample_price_message.txt'
OUTPUT_PATH = ROOT / 'data' / 'logs' / 'price_parser_test_output.json'
REQUIRED_ITEMS = {
    'Broccoli': 29.0,
    'Cauliflower': 28.0,
    'Carrot': 14.5,
    'Facai pumkin': 3.2,
}
MATCH_FIXTURES = [
    ({'item': 'Hk Kailan', 'unit': 'CTN', 'weight': '7kg', 'price': None}, 'HK Kailan', 0.9),
    ({'item': 'Icebrge lettuce', 'unit': 'CTN', 'weight': '10kg', 'price': None}, 'Iceberg Lettuce', 0.86),
    ({'item': 'Fresh Spring Onion', 'unit': 'PKT', 'weight': None, 'price': None}, 'Spring Onion', 0.9),
    ({'item': '#Red capsicum', 'unit': 'CTN', 'weight': None, 'price': None}, 'Red Capsicum', 0.9),
    ({'item': 'Suger Tangerine', 'unit': 'CTN', 'weight': '8kg', 'price': None}, 'Sugar Tangerine', 0.86),
]


def build_fixture_catalog(received_at: str) -> dict:
    return {
        'record_id': 'price_fixture_catalog',
        'received_at': received_at,
        'effective_price_date': '2026-03-06',
        'items': [
            {'item_name': 'HK Kailan', 'normalized_item': 'HK Kailan', 'pack_text': '7kg', 'price_basis': 'CTN', 'reference_price': 32.0, 'effective_price_date': '2026-03-06', 'received_at': received_at},
            {'item_name': 'Iceberg Lettuce', 'normalized_item': 'Iceberg Lettuce', 'pack_text': '10kg', 'price_basis': 'CTN', 'reference_price': 21.0, 'effective_price_date': '2026-03-06', 'received_at': received_at},
            {'item_name': 'Spring Onion', 'normalized_item': 'Spring Onion', 'pack_text': None, 'price_basis': 'PKT', 'reference_price': 4.8, 'effective_price_date': '2026-03-06', 'received_at': received_at},
            {'item_name': 'Red Capsicum', 'normalized_item': 'Red Capsicum', 'pack_text': None, 'price_basis': 'CTN', 'reference_price': 33.0, 'effective_price_date': '2026-03-06', 'received_at': received_at},
            {'item_name': 'Sugar Tangerine', 'normalized_item': 'Sugar Tangerine', 'pack_text': '8kg', 'price_basis': 'CTN', 'reference_price': 18.5, 'effective_price_date': '2026-03-06', 'received_at': received_at},
        ],
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

    fixture_catalog = build_fixture_catalog(received_at)
    match_results = []
    for item_row, expected_item, min_confidence in MATCH_FIXTURES:
        matched_entry, confidence = find_reference_match(item_row, fixture_catalog)
        if not matched_entry:
            raise SystemExit(f'No reference match found for: {item_row["item"]}')
        if matched_entry.get('normalized_item') != expected_item:
            raise SystemExit(f'Unexpected match for {item_row["item"]}: {matched_entry.get("normalized_item")}')
        if confidence is None or confidence < min_confidence:
            raise SystemExit(f'Confidence too low for {item_row["item"]}: {confidence}')
        match_results.append({
            'order_item': item_row['item'],
            'matched_item': matched_entry.get('normalized_item'),
            'confidence': confidence,
        })

    priced_items = [
        {'item': 'Suger Tangerine', 'unit': 'CTN', 'weight': '8kg', 'price': None, 'raw_line': 'Suger Tangerine 1 CTN'},
        {'item': 'Fresh Spring Onion', 'unit': 'PKT', 'weight': None, 'price': 9.9, 'raw_line': 'Fresh Spring Onion 2 PKT $9.90'},
    ]
    apply_reference_prices(priced_items, fixture_catalog)
    if priced_items[0]['price'] != 18.5:
        raise SystemExit(f'Blank order price was not filled from reference catalog: {priced_items[0]["price"]}')
    if priced_items[1]['price'] != 9.9:
        raise SystemExit(f'Existing manual price was overwritten: {priced_items[1]["price"]}')

    result['match_tests'] = match_results
    result['apply_reference_price_tests'] = priced_items
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding='utf-8')
    print(json.dumps(result, indent=2, ensure_ascii=False))
    print(f'\nSaved price parser test output to: {OUTPUT_PATH}')


if __name__ == '__main__':
    main()
