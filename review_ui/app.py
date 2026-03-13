from __future__ import annotations

import csv
import hashlib
import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from flask import Flask, jsonify, redirect, render_template, request, url_for

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from parser.price_parser import (  # noqa: E402
    LATEST_PRICES_PATH,
    PRICE_HISTORY_DIR,
    apply_reference_prices,
    load_latest_catalog,
)

DATA_DIR = ROOT / 'data'
INCOMING_DIR = DATA_DIR / 'incoming'
APPROVED_DIR = DATA_DIR / 'approved'
REJECTED_DIR = DATA_DIR / 'rejected'
LOG_DIR = DATA_DIR / 'logs'
for folder in (INCOMING_DIR, APPROVED_DIR, REJECTED_DIR, LOG_DIR):
    folder.mkdir(parents=True, exist_ok=True)

app = Flask(__name__)
app.secret_key = 'order-bot-local-dev'

logger = logging.getLogger('orderbot.review')
if not logger.handlers:
    logger.setLevel(logging.INFO)
    file_handler = logging.FileHandler(LOG_DIR / 'app.log')
    formatter = logging.Formatter('%(asctime)s | %(levelname)s | %(name)s | %(message)s')
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)


def read_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding='utf-8'))


def write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding='utf-8')


def pending_files() -> List[Path]:
    return sorted(INCOMING_DIR.glob('*.json'), key=lambda p: p.stat().st_mtime)


def load_history_records(folder: Path, *, timestamp_field: str, limit: int = 10) -> List[Dict[str, Any]]:
    if not folder.exists():
        return []

    records: List[Dict[str, Any]] = []
    for path in folder.glob('*.json'):
        try:
            record = read_json(path)
        except Exception:
            continue
        records.append(record)

    records.sort(
        key=lambda record: record.get(timestamp_field) or record.get('message_meta', {}).get('received_at') or '',
        reverse=True,
    )
    return records[:limit]


def enrich_record_with_prices(record: Dict[str, Any]) -> Dict[str, Any]:
    parse_result = record.get('parse_result')
    if not parse_result:
        return record

    latest_catalog = load_latest_catalog()
    items = parse_result.get('items', [])
    apply_reference_prices(items, latest_catalog)
    record['parse_result']['items'] = items
    record['latest_price_catalog'] = latest_catalog
    return record


def get_record(record_id: str) -> Optional[Dict[str, Any]]:
    path = INCOMING_DIR / f'{record_id}.json'
    if path.exists():
        return enrich_record_with_prices(read_json(path))
    return None


def latest_record_state(folder: Path, *, timestamp_field: str) -> Dict[str, Optional[str]]:
    json_files = list(folder.glob('*.json'))
    if not json_files:
        return {'record_id': None, 'timestamp': None, 'mtime_ns': None}

    latest_path = max(json_files, key=lambda path: path.stat().st_mtime_ns)
    latest_mtime_ns = str(latest_path.stat().st_mtime_ns)
    record_id = latest_path.stem
    timestamp = None

    try:
        record = read_json(latest_path)
        record_id = record.get('message_meta', {}).get('record_id') or record_id
        timestamp = record.get(timestamp_field) or record.get('message_meta', {}).get('received_at')
    except Exception:
        pass

    return {
        'record_id': record_id,
        'timestamp': timestamp,
        'mtime_ns': latest_mtime_ns,
    }


def format_file_mtime(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec='seconds')


def build_price_state() -> Dict[str, Optional[str]]:
    latest_catalog = load_latest_catalog()
    latest_prices_mtime_ns = None
    latest_prices_modified_at = None
    if LATEST_PRICES_PATH.exists():
        latest_prices_mtime_ns = str(LATEST_PRICES_PATH.stat().st_mtime_ns)
        latest_prices_modified_at = format_file_mtime(LATEST_PRICES_PATH)

    latest_history_file = None
    latest_history_mtime_ns = None
    latest_history_modified_at = None
    latest_history_effective_date = None
    history_files = list(PRICE_HISTORY_DIR.glob('*.json'))
    if history_files:
        latest_history_path = max(history_files, key=lambda path: path.stat().st_mtime_ns)
        latest_history_file = latest_history_path.name
        latest_history_mtime_ns = str(latest_history_path.stat().st_mtime_ns)
        latest_history_modified_at = format_file_mtime(latest_history_path)
        try:
            latest_history_record = read_json(latest_history_path)
            latest_history_effective_date = latest_history_record.get('price_result', {}).get('effective_price_date')
        except Exception:
            latest_history_effective_date = None

    return {
        'latest_prices_mtime_ns': latest_prices_mtime_ns,
        'latest_prices_modified_at': latest_prices_modified_at,
        'latest_price_history_file': latest_history_file,
        'latest_price_history_mtime_ns': latest_history_mtime_ns,
        'latest_price_history_modified_at': latest_history_modified_at,
        'latest_price_effective_date': latest_catalog.get('effective_price_date') or latest_history_effective_date,
        'latest_price_record_id': latest_catalog.get('record_id'),
        'latest_price_sender': latest_catalog.get('sender'),
    }


def build_dashboard_state() -> Dict[str, Any]:
    pending_state = [
        {
            'record_id': path.stem,
            'mtime_ns': str(path.stat().st_mtime_ns),
        }
        for path in pending_files()
    ]
    latest_pending_id = pending_state[-1]['record_id'] if pending_state else None
    latest_approved = latest_record_state(APPROVED_DIR, timestamp_field='approved_at')
    latest_rejected = latest_record_state(REJECTED_DIR, timestamp_field='rejected_at')
    price_state = build_price_state()

    fingerprint_source = {
        'pending': pending_state,
        'approved': latest_approved,
        'rejected': latest_rejected,
        'prices': price_state,
    }
    fingerprint = hashlib.sha256(
        json.dumps(fingerprint_source, sort_keys=True, separators=(',', ':')).encode('utf-8')
    ).hexdigest()

    return {
        'fingerprint': fingerprint,
        'queue_count': len(pending_state),
        'latest_pending_id': latest_pending_id,
        'latest_approved_id': latest_approved['record_id'],
        'latest_rejected_id': latest_rejected['record_id'],
        'latest_prices_mtime_ns': price_state['latest_prices_mtime_ns'],
        'latest_prices_modified_at': price_state['latest_prices_modified_at'],
        'latest_price_history_file': price_state['latest_price_history_file'],
        'latest_price_history_mtime_ns': price_state['latest_price_history_mtime_ns'],
        'latest_price_history_modified_at': price_state['latest_price_history_modified_at'],
        'latest_price_effective_date': price_state['latest_price_effective_date'],
        'latest_price_record_id': price_state['latest_price_record_id'],
        'latest_price_sender': price_state['latest_price_sender'],
        'price_state': price_state,
    }


def update_from_form(record: Dict[str, Any], form_data) -> Dict[str, Any]:
    customer = form_data.get('customer', '').strip() or None
    parse_result = record['parse_result']
    raw_message = form_data.get('raw_message', parse_result.get('raw_message', ''))
    rows: List[Dict[str, Any]] = []
    row_count = int(form_data.get('row_count', 0))

    for idx in range(row_count):
        item = form_data.get(f'item_{idx}', '').strip()
        raw_line = form_data.get(f'raw_line_{idx}', '').strip()
        if not item and not raw_line:
            continue
        quantity_raw = form_data.get(f'quantity_{idx}', '').strip()
        price_raw = form_data.get(f'price_{idx}', '').strip()
        row = {
            'customer': customer,
            'item': item,
            'quantity': int(float(quantity_raw)) if quantity_raw and float(quantity_raw).is_integer() else (float(quantity_raw) if quantity_raw else None),
            'unit': form_data.get(f'unit_{idx}', 'CTN').strip().upper() or 'CTN',
            'weight': form_data.get(f'weight_{idx}', '').strip() or None,
            'price': float(price_raw) if price_raw else None,
            'raw_line': raw_line or item,
        }
        rows.append(row)

    parse_result['customer'] = customer
    parse_result['raw_message'] = raw_message
    parse_result['items'] = rows
    parse_result['status'] = 'parsed' if rows else 'needs_review'
    parse_result['stats'] = {
        'item_count': len(rows),
        'unparsed_count': 0,
    }
    record['parse_result'] = parse_result
    return enrich_record_with_prices(record)


def write_csv(path: Path, rows: List[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', newline='', encoding='utf-8') as fh:
        writer = csv.DictWriter(fh, fieldnames=['customer', 'item', 'quantity', 'unit', 'weight', 'price', 'raw_line'])
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def archive_raw_text(target_dir: Path, record: Dict[str, Any]) -> None:
    raw_dir = target_dir / 'raw_messages'
    raw_dir.mkdir(parents=True, exist_ok=True)
    record_id = record['message_meta']['record_id']
    raw_text = record['parse_result'].get('raw_message', '')
    (raw_dir / f'{record_id}.txt').write_text(raw_text, encoding='utf-8')


def append_decision_log(record: Dict[str, Any], decision: str) -> None:
    path = LOG_DIR / 'review_actions.csv'
    exists = path.exists()
    with path.open('a', newline='', encoding='utf-8') as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=['record_id', 'decision', 'customer', 'item_count', 'timestamp'],
        )
        if not exists:
            writer.writeheader()
        writer.writerow(
            {
                'record_id': record['message_meta']['record_id'],
                'decision': decision,
                'customer': record['parse_result'].get('customer'),
                'item_count': len(record['parse_result'].get('items', [])),
                'timestamp': datetime.now().isoformat(timespec='seconds'),
            }
        )


@app.route('/')
def index():
    dashboard_state = build_dashboard_state()
    queue = [enrich_record_with_prices(read_json(path)) for path in pending_files()]
    approved_history = load_history_records(APPROVED_DIR, timestamp_field='approved_at', limit=10)
    rejected_history = load_history_records(REJECTED_DIR, timestamp_field='rejected_at', limit=10)
    return render_template(
        'index.html',
        queue=queue,
        approved_history=approved_history,
        rejected_history=rejected_history,
        price_summary=dashboard_state['price_state'],
        dashboard_state=dashboard_state,
        dashboard_fingerprint=dashboard_state['fingerprint'],
    )


@app.route('/api/dashboard_state')
def dashboard_state_api():
    return jsonify(build_dashboard_state())


@app.route('/review/<record_id>', methods=['GET', 'POST'])
def review(record_id: str):
    record = get_record(record_id)
    if not record:
        return redirect(url_for('index'))

    if request.method == 'POST':
        action = request.form.get('action')
        record = update_from_form(record, request.form)
        src = INCOMING_DIR / f'{record_id}.json'

        if action == 'save':
            write_json(src, record)
            logger.info('saved_review_draft record_id=%s', record_id)
            return redirect(url_for('review', record_id=record_id))

        if action == 'approve':
            output_json = APPROVED_DIR / f'{record_id}.json'
            output_csv = APPROVED_DIR / f'{record_id}.csv'
            record['review_state'] = 'approved'
            record['approved_at'] = datetime.now().isoformat(timespec='seconds')
            write_json(output_json, record)
            write_csv(output_csv, record['parse_result'].get('items', []))
            archive_raw_text(APPROVED_DIR, record)
            src.unlink(missing_ok=True)
            append_decision_log(record, 'approved')
            logger.info('approved_order record_id=%s items=%s', record_id, len(record['parse_result'].get('items', [])))
            return redirect(url_for('index'))

        if action == 'reject':
            record['review_state'] = 'rejected'
            record['rejected_at'] = datetime.now().isoformat(timespec='seconds')
            output_json = REJECTED_DIR / f'{record_id}.json'
            write_json(output_json, record)
            archive_raw_text(REJECTED_DIR, record)
            src.unlink(missing_ok=True)
            append_decision_log(record, 'rejected')
            logger.info('rejected_order record_id=%s', record_id)
            return redirect(url_for('index'))

    return render_template('review.html', record=record)


if __name__ == '__main__':
    app.run(debug=True, port=5001)
