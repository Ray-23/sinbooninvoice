from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from parser.order_parser import parse_message  # noqa: E402
from parser.price_parser import (  # noqa: E402
    LATEST_PRICES_PATH,
    PRICE_HISTORY_DIR,
    PRICE_RAW_DIR,
    apply_reference_prices,
    build_latest_catalog,
    ensure_price_directories,
    load_latest_catalog,
    parse_price_message,
    should_replace_latest_catalog,
)

DATA_DIR = ROOT / 'data'
INCOMING_DIR = DATA_DIR / 'incoming'
LOG_DIR = DATA_DIR / 'logs'
LOG_DIR.mkdir(parents=True, exist_ok=True)

logger = logging.getLogger('orderbot.ingest')
if not logger.handlers:
    logger.setLevel(logging.INFO)
    file_handler = logging.FileHandler(LOG_DIR / 'app.log')
    formatter = logging.Formatter('%(asctime)s | %(levelname)s | %(name)s | %(message)s')
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)


def make_id(prefix: str = 'msg') -> str:
    return f"{prefix}_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid4().hex[:8]}"


def save_parse_event(record: dict) -> Path:
    INCOMING_DIR.mkdir(parents=True, exist_ok=True)
    record_id = record['message_meta']['record_id']
    path = INCOMING_DIR / f'{record_id}.json'
    path.write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding='utf-8')
    return path


def append_csv_log(record: dict) -> None:
    path = LOG_DIR / 'incoming_index.csv'
    file_exists = path.exists()
    with path.open('a', newline='', encoding='utf-8') as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=['record_id', 'source', 'group_name', 'sender', 'status', 'item_count', 'received_at'],
        )
        if not file_exists:
            writer.writeheader()
        writer.writerow(
            {
                'record_id': record['message_meta']['record_id'],
                'source': record['message_meta']['source'],
                'group_name': record['message_meta'].get('group_name'),
                'sender': record['message_meta'].get('sender'),
                'status': record['parse_result']['status'],
                'item_count': record['parse_result']['stats']['item_count'],
                'received_at': record['message_meta']['received_at'],
            }
        )


def save_price_raw(record_id: str, raw_message: str) -> Path:
    ensure_price_directories()
    path = PRICE_RAW_DIR / f'{record_id}.txt'
    path.write_text(raw_message, encoding='utf-8')
    return path


def save_price_history(record: dict) -> Path:
    ensure_price_directories()
    path = PRICE_HISTORY_DIR / f"{record['message_meta']['record_id']}.json"
    path.write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding='utf-8')
    return path


def update_latest_price_catalog(record: dict) -> tuple[Path, bool]:
    ensure_price_directories()
    latest_catalog = build_latest_catalog(record)
    current_catalog = load_latest_catalog()
    should_update = should_replace_latest_catalog(latest_catalog, current_catalog)
    if should_update:
        LATEST_PRICES_PATH.write_text(json.dumps(latest_catalog, indent=2, ensure_ascii=False), encoding='utf-8')
    return LATEST_PRICES_PATH, should_update


def ingest_order_message(args, raw: str, received_at: str) -> dict:
    result = parse_message(raw)
    apply_reference_prices(result['items'])
    record_id = make_id()
    record = {
        'message_meta': {
            'record_id': record_id,
            'source': args.source,
            'chat_id': args.chat_id,
            'group_name': args.group_name,
            'sender': args.sender,
            'message_id': args.message_id,
            'received_at': received_at,
        },
        'parse_result': result,
        'review_state': 'pending',
    }

    path = save_parse_event(record)
    append_csv_log(record)
    logger.info(
        'received_order_message record_id=%s source=%s group=%s sender=%s status=%s item_count=%s',
        record_id,
        args.source,
        args.group_name,
        args.sender,
        result['status'],
        result['stats']['item_count'],
    )
    return {
        'ok': True,
        'message_type': 'order',
        'record_id': record_id,
        'saved_to': str(path),
    }


def ingest_price_message(args, raw: str, received_at: str) -> dict:
    result = parse_price_message(raw, received_at)
    record_id = make_id(prefix='price')
    record = {
        'message_meta': {
            'record_id': record_id,
            'source': args.source,
            'chat_id': args.chat_id,
            'group_name': args.group_name,
            'sender': args.sender,
            'message_id': args.message_id,
            'received_at': received_at,
        },
        'price_result': result,
    }

    raw_path = save_price_raw(record_id, raw)
    history_path = save_price_history(record)
    latest_catalog_path, latest_updated = update_latest_price_catalog(record)
    logger.info(
        'received_price_message record_id=%s source=%s group=%s sender=%s status=%s item_count=%s effective_date=%s latest_updated=%s',
        record_id,
        args.source,
        args.group_name,
        args.sender,
        result['status'],
        result['stats']['item_count'],
        result['effective_price_date'],
        latest_updated,
    )
    return {
        'ok': True,
        'message_type': 'price',
        'record_id': record_id,
        'saved_raw_to': str(raw_path),
        'saved_history_to': str(history_path),
        'latest_catalog_path': str(latest_catalog_path),
        'latest_catalog_updated': latest_updated,
        'effective_price_date': result['effective_price_date'],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description='Ingest one raw message into the order-bot pipeline')
    parser.add_argument('--source', default='manual')
    parser.add_argument('--chat-id', default='')
    parser.add_argument('--group-name', default='')
    parser.add_argument('--sender', default='')
    parser.add_argument('--message-id', default='')
    parser.add_argument('--message-type', choices=['order', 'price'], default='order')
    parser.add_argument('--stdin', action='store_true', help='Read raw message text from stdin')
    args = parser.parse_args()

    raw = sys.stdin.read() if args.stdin else ''
    raw = raw.strip()
    if not raw:
        raise SystemExit('No message text received. Pipe message text into stdin and use --stdin.')

    received_at = datetime.now().replace(microsecond=0).isoformat()
    if args.message_type == 'price':
        output = ingest_price_message(args, raw, received_at)
    else:
        output = ingest_order_message(args, raw, received_at)

    print(json.dumps(output, indent=2))


if __name__ == '__main__':
    main()
