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


def build_latest_catalog(record: Dict[str, Any]) -> Dict[str, Any]:
    price_result = record['price_result']
    return {
        'record_id': record['message_meta']['record_id'],
        'group_name': record['message_meta'].get('group_name'),
        'sender': record['message_meta'].get('sender'),
        'message_id': record['message_meta'].get('message_id'),
        'received_at': record['message_meta']['received_at'],
        'effective_price_date': price_result['effective_price_date'],
        'header_line': price_result['header_line'],
        'raw_text_path': str(PRICE_RAW_DIR / f"{record['message_meta']['record_id']}.txt"),
        'history_path': str(PRICE_HISTORY_DIR / f"{record['message_meta']['record_id']}.json"),
        'items': price_result['items'],
    }


def load_latest_catalog() -> Dict[str, Any]:
    if not LATEST_PRICES_PATH.exists():
        return {}
    try:
        return json.loads(LATEST_PRICES_PATH.read_text(encoding='utf-8'))
    except Exception:
        return {}


def should_replace_latest_catalog(candidate: Dict[str, Any], current: Dict[str, Any]) -> bool:
    if not current:
        return True

    candidate_date = candidate.get('effective_price_date') or ''
    current_date = current.get('effective_price_date') or ''
    if candidate_date != current_date:
        return candidate_date > current_date

    candidate_received = candidate.get('received_at') or ''
    current_received = current.get('received_at') or ''
    return candidate_received > current_received


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
    exact_candidates: List[Tuple[float, Dict[str, Any]]] = []
    fuzzy_candidates: List[Tuple[float, Dict[str, Any]]] = []

    for entry in catalog.get('items', []):
        entry_name = str(entry.get('normalized_item') or entry.get('item_name') or '').strip()
        normalized_entry_name = normalize_alias(entry_name, item_aliases) or entry_name
        entry_key = canonical_item_key(normalized_entry_name)
        if not entry_key:
            continue

        entry_pack = normalize_pack_text(entry.get('pack_text'))
        entry_basis = str(entry.get('price_basis') or '').strip().upper()

        if entry_key == order_key:
            exact_candidates.append((exact_match_confidence(order_weight, order_unit, entry_pack, entry_basis), entry))
            continue

        base_similarity = similarity_ratio(order_key, entry_key)
        if base_similarity < FUZZY_MATCH_THRESHOLD:
            continue

        confidence = fuzzy_match_confidence(base_similarity, order_weight, order_unit, entry_pack, entry_basis)
        if confidence < FUZZY_MATCH_THRESHOLD:
            continue
        fuzzy_candidates.append((confidence, entry))

    candidates = exact_candidates or fuzzy_candidates
    if not candidates:
        return None, None

    best_score, best_match = max(
        candidates,
        key=lambda pair: (
            pair[0],
            str(pair[1].get('effective_price_date') or ''),
            str(pair[1].get('received_at') or ''),
            str(pair[1].get('normalized_item') or pair[1].get('item_name') or ''),
        ),
    )
    return best_match, best_score


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
