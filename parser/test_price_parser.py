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


def build_catalog(received_at: str, items: list[dict]) -> dict:
    return {
        'record_id': 'price_fixture_catalog',
        'received_at': received_at,
        'effective_price_date': '2026-03-06',
        'items': [
            {
                'item_name': item['item_name'],
                'normalized_item': item['normalized_item'],
                'pack_text': item.get('pack_text'),
                'price_basis': item.get('price_basis', 'CTN'),
                'reference_price': item['reference_price'],
                'effective_price_date': item.get('effective_price_date', '2026-03-06'),
                'received_at': received_at,
            }
            for item in items
        ],
    }


def build_fixture_catalog(received_at: str) -> dict:
    return build_catalog(
        received_at,
        [
            {'item_name': 'HK Kailan', 'normalized_item': 'HK Kailan', 'pack_text': '7kg', 'price_basis': 'CTN', 'reference_price': 32.0},
            {'item_name': 'Iceberg Lettuce', 'normalized_item': 'Iceberg Lettuce', 'pack_text': '10kg', 'price_basis': 'CTN', 'reference_price': 21.0},
            {'item_name': 'Spring Onion', 'normalized_item': 'Spring Onion', 'pack_text': None, 'price_basis': 'PKT', 'reference_price': 4.8},
            {'item_name': 'Red Capsicum', 'normalized_item': 'Red Capsicum', 'pack_text': None, 'price_basis': 'CTN', 'reference_price': 33.0},
            {'item_name': 'Sugar Tangerine', 'normalized_item': 'Sugar Tangerine', 'pack_text': '8kg', 'price_basis': 'CTN', 'reference_price': 18.5},
        ],
    )


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

    single_variant_catalog = build_catalog(
        received_at,
        [
            {'item_name': 'Suger Tangerine', 'normalized_item': 'Sugar Tangerine', 'pack_text': '6kg', 'price_basis': 'CTN', 'reference_price': 28.0},
        ],
    )
    single_variant_match, single_variant_confidence = find_reference_match(
        {'item': 'Suger Tangerine', 'unit': 'CTN', 'weight': None, 'price': None, 'raw_line': 'Suger tangerine 10ctn'},
        single_variant_catalog,
    )
    if not single_variant_match or single_variant_match.get('pack_text') != '6kg':
        raise SystemExit('Single-variant fallback did not match the only available Sugar Tangerine price.')
    if single_variant_confidence is None or single_variant_confidence < 0.86:
        raise SystemExit(f'Single-variant fallback confidence too low: {single_variant_confidence}')

    one_side_weight_only_catalog = build_catalog(
        received_at,
        [
            {'item_name': 'Sugar Tangerine', 'normalized_item': 'Sugar Tangerine', 'pack_text': None, 'price_basis': 'CTN', 'reference_price': 24.0},
        ],
    )
    one_side_only_match, _ = find_reference_match(
        {'item': 'Sugar Tangerine', 'unit': 'CTN', 'weight': '10kg', 'price': None, 'raw_line': 'Sugar Tangerine 10kg 1 CTN'},
        one_side_weight_only_catalog,
    )
    if not one_side_only_match or one_side_only_match.get('reference_price') != 24.0:
        raise SystemExit('One-side-weight-only single-variant fallback did not match.')

    multi_variant_catalog = build_catalog(
        received_at,
        [
            {'item_name': 'Sugar Tangerine', 'normalized_item': 'Sugar Tangerine', 'pack_text': '6kg', 'price_basis': 'CTN', 'reference_price': 20.0},
            {'item_name': 'Sugar Tangerine', 'normalized_item': 'Sugar Tangerine', 'pack_text': '10kg', 'price_basis': 'CTN', 'reference_price': 30.0},
        ],
    )
    ambiguous_match, ambiguous_confidence = find_reference_match(
        {'item': 'Sugar Tangerine', 'unit': 'CTN', 'weight': None, 'price': None, 'raw_line': 'Sugar Tangerine'},
        multi_variant_catalog,
    )
    if ambiguous_match is not None or ambiguous_confidence is not None:
        raise SystemExit('Ambiguous multi-variant catalog should not auto-match without order weight.')

    exact_variant_match, exact_variant_confidence = find_reference_match(
        {'item': 'Sugar Tangerine', 'unit': 'CTN', 'weight': '10kg', 'price': None, 'raw_line': 'Sugar Tangerine 10kg'},
        multi_variant_catalog,
    )
    if not exact_variant_match or exact_variant_match.get('pack_text') != '10kg':
        raise SystemExit('Exact weight variant did not match the 10kg Sugar Tangerine price.')
    if exact_variant_confidence is None or exact_variant_confidence < 0.9:
        raise SystemExit(f'Exact weight variant confidence too low: {exact_variant_confidence}')

    ambiguous_items = [
        {'item': 'Sugar Tangerine', 'unit': 'CTN', 'weight': None, 'price': None, 'raw_line': 'Sugar Tangerine 1 CTN'},
    ]
    apply_reference_prices(ambiguous_items, multi_variant_catalog)
    if ambiguous_items[0]['price'] is not None or ambiguous_items[0]['reference_price'] is not None:
        raise SystemExit('Ambiguous multi-variant order should not be auto-filled.')

    result['match_tests'] = match_results
    result['apply_reference_price_tests'] = priced_items
    result['single_variant_fallback_test'] = {
        'matched_item': single_variant_match.get('normalized_item'),
        'matched_pack': single_variant_match.get('pack_text'),
        'confidence': single_variant_confidence,
    }
    result['one_side_weight_only_test'] = {
        'matched_item': one_side_only_match.get('normalized_item'),
        'matched_pack': one_side_only_match.get('pack_text'),
    }
    result['multi_variant_ambiguous_test'] = {
        'matched': ambiguous_match is not None,
        'confidence': ambiguous_confidence,
        'auto_filled_price': ambiguous_items[0]['price'],
    }
    result['multi_variant_exact_test'] = {
        'matched_item': exact_variant_match.get('normalized_item'),
        'matched_pack': exact_variant_match.get('pack_text'),
        'confidence': exact_variant_confidence,
    }
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding='utf-8')
    print(json.dumps(result, indent=2, ensure_ascii=False))
    print(f'\nSaved price parser test output to: {OUTPUT_PATH}')


if __name__ == '__main__':
    main()
