from __future__ import annotations

import json
import re
from datetime import date, datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from parser.order_parser import DATA_DIR, clean_item_name, load_mappings, normalize_alias

PRICE_DATA_DIR = DATA_DIR / 'prices'
PRICE_RAW_DIR = PRICE_DATA_DIR / 'raw'
PRICE_HISTORY_DIR = PRICE_DATA_DIR / 'history'
LATEST_PRICES_PATH = PRICE_DATA_DIR / 'latest_prices.json'
FUZZY_MATCH_THRESHOLD = 0.86

DATE_LINE_RE = re.compile(r'^\s*(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?')
PRICE_RE = re.compile(r'(?:\$|rm\s*)(\d+(?:\.\d{1,2})?)(?:\s*/\s*([a-zA-Z]+))?\.?', re.IGNORECASE)
PACK_RE = re.compile(r'(?P<pack>(?:\d+(?:\.\d+)?)\s*(?:kg|g|pkt|pcs|pc|ctn|carton|bag|box|jar))\.?$', re.IGNORECASE)

PRICE_BASIS_ALIASES = {
    'carton': 'CTN',
    'cartons': 'CTN',
    'ctn': 'CTN',
    'bag': 'BAG',
    'bags': 'BAG',
    'box': 'BOX',
    'boxes': 'BOX',
    'pkt': 'PKT',
    'pkts': 'PKT',
    'packet': 'PKT',
    'packets': 'PKT',
    'pcs': 'PCS',
    'pc': 'PCS',
    'piece': 'PCS',
    'pieces': 'PCS',
    'kg': 'KG',
    'kgs': 'KG',
    'jar': 'JAR',
    'jars': 'JAR',
}


def ensure_price_directories() -> None:
    for folder in (PRICE_DATA_DIR, PRICE_RAW_DIR, PRICE_HISTORY_DIR):
        folder.mkdir(parents=True, exist_ok=True)


def canonical_item_key(value: Optional[str]) -> str:
    if not value:
        return ''
    cleaned = re.sub(r'[^a-z0-9]+', ' ', value.lower())
    return re.sub(r'\s+', ' ', cleaned).strip()


def normalize_price_basis(raw_basis: Optional[str]) -> str:
    if not raw_basis:
        return 'CTN'
    return PRICE_BASIS_ALIASES.get(raw_basis.strip().lower().rstrip('.'), 'CTN')


def normalize_pack_text(pack_text: Optional[str]) -> Optional[str]:
    if not pack_text:
        return None
    return re.sub(r'\s+', '', pack_text.strip().lower().rstrip('.'))


def similarity_ratio(left: str, right: str) -> float:
    if not left or not right:
        return 0.0

    left_compact = left.replace(' ', '')
    right_compact = right.replace(' ', '')
    scores = [SequenceMatcher(None, left, right).ratio()]
    if left_compact != left or right_compact != right:
        scores.append(SequenceMatcher(None, left_compact, right_compact).ratio())
    return max(scores)


def pack_score_adjustment(order_weight: Optional[str], entry_pack: Optional[str]) -> float:
    if order_weight and entry_pack:
        return 0.04 if order_weight == entry_pack else -0.10
    if order_weight and not entry_pack:
        return -0.02
    if entry_pack and not order_weight:
        return -0.04
    return 0.0


def basis_score_adjustment(order_unit: str, entry_basis: str) -> float:
    if order_unit and entry_basis:
        return 0.02 if order_unit == entry_basis else -0.05
    return 0.0


def clamp_confidence(score: float) -> float:
    return round(max(0.0, min(score, 1.0)), 2)


def exact_match_confidence(order_weight: Optional[str], order_unit: str, entry_pack: Optional[str], entry_basis: str) -> float:
    score = 0.97
    score += pack_score_adjustment(order_weight, entry_pack)
    score += basis_score_adjustment(order_unit, entry_basis)
    return clamp_confidence(score)


def fuzzy_match_confidence(base_similarity: float, order_weight: Optional[str], order_unit: str, entry_pack: Optional[str], entry_basis: str) -> float:
    score = base_similarity
    score += pack_score_adjustment(order_weight, entry_pack) * 0.5
    score += basis_score_adjustment(order_unit, entry_basis) * 0.5
    return clamp_confidence(score)


def build_match_candidate(
    entry: Dict[str, Any],
    item_aliases: Dict[str, str],
    order_key: str,
    order_weight: Optional[str],
    order_unit: str,
) -> Optional[Dict[str, Any]]:
    entry_name = str(entry.get('normalized_item') or entry.get('item_name') or '').strip()
    normalized_entry_name = normalize_alias(entry_name, item_aliases) or entry_name
    entry_key = canonical_item_key(normalized_entry_name)
    if not entry_key:
        return None

    entry_pack = normalize_pack_text(entry.get('pack_text'))
    entry_basis = str(entry.get('price_basis') or '').strip().upper()

    if entry_key == order_key:
        return {
            'entry': entry,
            'entry_key': entry_key,
            'entry_pack': entry_pack,
            'name_score': 1.0,
            'confidence': exact_match_confidence(order_weight, order_unit, entry_pack, entry_basis),
        }

    base_similarity = similarity_ratio(order_key, entry_key)
    if base_similarity < FUZZY_MATCH_THRESHOLD:
        return None

    confidence = fuzzy_match_confidence(base_similarity, order_weight, order_unit, entry_pack, entry_basis)
    if confidence < FUZZY_MATCH_THRESHOLD:
        return None

    return {
        'entry': entry,
        'entry_key': entry_key,
        'entry_pack': entry_pack,
        'name_score': base_similarity,
        'confidence': confidence,
    }


def select_item_name_group(candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not candidates:
        return []

    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for candidate in candidates:
        grouped.setdefault(candidate['entry_key'], []).append(candidate)

    ranked_groups = sorted(
        grouped.values(),
        key=lambda group: (
            max(candidate['name_score'] for candidate in group),
            max(candidate['confidence'] for candidate in group),
            group[0]['entry_key'],
        ),
        reverse=True,
    )
    return ranked_groups[0]


def select_variant_candidate(candidates: List[Dict[str, Any]], order_weight: Optional[str]) -> Tuple[Optional[Dict[str, Any]], Optional[float]]:
    if not candidates:
        return None, None

    if len(candidates) == 1:
        only_candidate = candidates[0]
        return only_candidate['entry'], only_candidate['confidence']

    if not order_weight:
        return None, None

    weight_matches = [candidate for candidate in candidates if candidate.get('entry_pack') == order_weight]
    if not weight_matches:
        return None, None

    best_candidate = max(
        weight_matches,
        key=lambda candidate: (
            candidate['confidence'],
            str(candidate['entry'].get('effective_price_date') or ''),
            str(candidate['entry'].get('received_at') or ''),
            str(candidate['entry'].get('normalized_item') or candidate['entry'].get('item_name') or ''),
        ),
    )
    return best_candidate['entry'], best_candidate['confidence']


def parse_effective_price_date(header_line: str, received_at: str) -> str:
    match = DATE_LINE_RE.match(header_line or '')
    if not match:
        raise ValueError('Price message first line must start with a date like 6/3 or 6/3/2026.')

    day = int(match.group(1))
    month = int(match.group(2))
    raw_year = match.group(3)
    if raw_year:
        year = int(raw_year)
        if year < 100:
            year += 2000
    else:
        year = datetime.fromisoformat(received_at).year

    return date(year, month, day).isoformat()


def parse_price_line(line: str, effective_price_date: str, received_at: str, item_aliases: Dict[str, str]) -> Optional[Dict[str, Any]]:
    raw_line = re.sub(r'\s+', ' ', line or '').strip()
    if not raw_line:
        return None

    price_match = PRICE_RE.search(raw_line)
    if not price_match:
        return None

    reference_price = float(price_match.group(1))
    price_basis = normalize_price_basis(price_match.group(2))
    before_price = raw_line[:price_match.start()].strip(' .,:;\t\n\r-')

    pack_text = None
    item_source = before_price
    pack_match = PACK_RE.search(before_price)
    if pack_match:
        pack_text = re.sub(r'\s+', '', pack_match.group('pack').strip().rstrip('.'))
        item_source = before_price[:pack_match.start()].strip(' .,:;\t\n\r-')

    item_name = clean_item_name(item_source)
    if not item_name:
        return None

    normalized_item = normalize_alias(item_name, item_aliases) or item_name

    return {
        'raw_line': raw_line,
        'item_name': item_name,
        'normalized_item': normalized_item,
        'pack_text': pack_text,
        'reference_price': reference_price,
        'price_basis': price_basis,
        'effective_price_date': effective_price_date,
        'received_at': received_at,
    }


def parse_price_message(raw_message: str, received_at: str) -> Dict[str, Any]:
    _, item_aliases = load_mappings()
    lines = [re.sub(r'\s+', ' ', line).strip() for line in (raw_message or '').splitlines()]
    meaningful = [line for line in lines if line]
    if not meaningful:
        raise ValueError('Price message is empty.')

    header_line = meaningful[0]
    effective_price_date = parse_effective_price_date(header_line, received_at)
    items: List[Dict[str, Any]] = []
    unparsed_lines: List[str] = []

    for line in meaningful[1:]:
        parsed = parse_price_line(line, effective_price_date, received_at, item_aliases)
        if parsed:
            items.append(parsed)
        else:
            unparsed_lines.append(line)

    return {
        'header_line': header_line,
        'effective_price_date': effective_price_date,
        'raw_message': raw_message,
        'items': items,
        'unparsed_lines': unparsed_lines,
        'status': 'parsed' if items else 'needs_review',
        'stats': {
            'item_count': len(items),
            'unparsed_count': len(unparsed_lines),
        },
    }


def price_record_effective_date(record: Dict[str, Any]) -> str:
    return str(record.get('price_result', {}).get('effective_price_date') or '')


def price_record_received_at(record: Dict[str, Any]) -> str:
    return str(record.get('message_meta', {}).get('received_at') or '')


def load_price_history_records() -> List[Dict[str, Any]]:
    if not PRICE_HISTORY_DIR.exists():
        return []

    records: List[Dict[str, Any]] = []
    for path in PRICE_HISTORY_DIR.glob('*.json'):
        try:
            record = json.loads(path.read_text(encoding='utf-8'))
        except Exception:
            continue
        record['_history_path'] = str(path)
        records.append(record)
    return records


def build_price_variant_key(entry: Dict[str, Any], item_aliases: Dict[str, str]) -> str:
    entry_name = str(entry.get('normalized_item') or entry.get('item_name') or '').strip()
    normalized_entry_name = normalize_alias(entry_name, item_aliases) or entry_name
    canonical_name = canonical_item_key(normalized_entry_name)
    pack_text = normalize_pack_text(entry.get('pack_text')) or ''
    price_basis = str(entry.get('price_basis') or '').strip().upper() or 'CTN'
    return f'{canonical_name}|{pack_text}|{price_basis}'


def build_latest_catalog(history_records: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    ensure_price_directories()
    records = history_records if history_records is not None else load_price_history_records()
    valid_records = [record for record in records if price_record_effective_date(record)]
    if not valid_records:
        return {}

    active_effective_date = max(price_record_effective_date(record) for record in valid_records)
    active_records = [record for record in valid_records if price_record_effective_date(record) == active_effective_date]
    active_records.sort(
        key=lambda record: (
            price_record_received_at(record),
            str(record.get('message_meta', {}).get('record_id') or ''),
        )
    )

    _, item_aliases = load_mappings()
    merged_variants: Dict[str, Dict[str, Any]] = {}
    active_record_ids: List[str] = []
    active_history_files: List[str] = []

    for record in active_records:
        message_meta = record.get('message_meta', {})
        price_result = record.get('price_result', {})
        record_id = str(message_meta.get('record_id') or '')
        if record_id:
            active_record_ids.append(record_id)
            active_history_files.append(str(PRICE_HISTORY_DIR / f'{record_id}.json'))

        for item in price_result.get('items', []):
            variant_key = build_price_variant_key(item, item_aliases)
            if not variant_key:
                continue

            merged_item = dict(item)
            merged_item['normalized_item'] = normalize_alias(
                str(item.get('normalized_item') or item.get('item_name') or '').strip(),
                item_aliases,
            ) or str(item.get('normalized_item') or item.get('item_name') or '').strip()
            merged_item['pack_text'] = normalize_pack_text(item.get('pack_text'))
            merged_item['price_basis'] = str(item.get('price_basis') or '').strip().upper() or 'CTN'
            merged_item['variant_key'] = variant_key
            merged_item['source_record_id'] = record_id or None
            merged_item['source_received_at'] = price_record_received_at(record) or None
            merged_item['source_sender'] = message_meta.get('sender')
            merged_item['source_group_name'] = message_meta.get('group_name')

            existing = merged_variants.get(variant_key)
            existing_received_at = str(existing.get('received_at') or existing.get('source_received_at') or '') if existing else ''
            candidate_received_at = str(merged_item.get('received_at') or merged_item.get('source_received_at') or '')
            if not existing or candidate_received_at >= existing_received_at:
                merged_variants[variant_key] = merged_item

    latest_record = active_records[-1]
    latest_meta = latest_record.get('message_meta', {})
    latest_result = latest_record.get('price_result', {})
    merged_items = sorted(
        merged_variants.values(),
        key=lambda item: (
            canonical_item_key(item.get('normalized_item') or item.get('item_name')),
            normalize_pack_text(item.get('pack_text')) or '',
            str(item.get('price_basis') or '').strip().upper(),
        ),
    )

    latest_record_id = latest_meta.get('record_id')
    return {
        'record_id': latest_record_id,
        'group_name': latest_meta.get('group_name'),
        'sender': latest_meta.get('sender'),
        'message_id': latest_meta.get('message_id'),
        'received_at': latest_meta.get('received_at'),
        'effective_price_date': active_effective_date,
        'header_line': latest_result.get('header_line'),
        'raw_text_path': str(PRICE_RAW_DIR / f'{latest_record_id}.txt') if latest_record_id else None,
        'history_path': str(PRICE_HISTORY_DIR / f'{latest_record_id}.json') if latest_record_id else None,
        'active_history_files': active_history_files,
        'active_record_ids': active_record_ids,
        'source_message_count': len(active_records),
        'item_count': len(merged_items),
        'items': merged_items,
    }


def rebuild_latest_catalog() -> Dict[str, Any]:
    ensure_price_directories()
    latest_catalog = build_latest_catalog()
    LATEST_PRICES_PATH.write_text(json.dumps(latest_catalog, indent=2, ensure_ascii=False), encoding='utf-8')
    return latest_catalog


def load_latest_catalog() -> Dict[str, Any]:
    if not LATEST_PRICES_PATH.exists():
        return rebuild_latest_catalog()
    try:
        catalog = json.loads(LATEST_PRICES_PATH.read_text(encoding='utf-8'))
    except Exception:
        return rebuild_latest_catalog()
    if catalog and 'active_record_ids' not in catalog:
        return rebuild_latest_catalog()
    return catalog


def find_reference_match(item_row: Dict[str, Any], catalog: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], Optional[float]]:
    if not catalog:
        return None, None

    _, item_aliases = load_mappings()
    item_name = str(item_row.get('item') or '').strip()
    normalized_item = normalize_alias(item_name, item_aliases) or item_name
    order_key = canonical_item_key(normalized_item)
    if not order_key:
        return None, None

    order_weight = normalize_pack_text(item_row.get('weight'))
    order_unit = str(item_row.get('unit') or '').strip().upper()
    candidates: List[Dict[str, Any]] = []

    for entry in catalog.get('items', []):
        candidate = build_match_candidate(entry, item_aliases, order_key, order_weight, order_unit)
        if candidate:
            candidates.append(candidate)

    matched_item_group = select_item_name_group(candidates)
    if not matched_item_group:
        return None, None

    return select_variant_candidate(matched_item_group, order_weight)


def apply_reference_prices(items: List[Dict[str, Any]], catalog: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    latest_catalog = catalog if catalog is not None else load_latest_catalog()
    for item in items:
        match, confidence = find_reference_match(item, latest_catalog)
        if match:
            item['reference_price'] = match['reference_price']
            item['reference_price_basis'] = match['price_basis']
            item['reference_price_date'] = match['effective_price_date']
            item['reference_price_item'] = match.get('normalized_item') or match.get('item_name')
            item['price_match_confidence'] = confidence
            if item.get('price') in (None, ''):
                item['price'] = match['reference_price']
        else:
            item['reference_price'] = None
            item['reference_price_basis'] = None
            item['reference_price_date'] = None
            item['reference_price_item'] = None
            item['price_match_confidence'] = None
    return items
