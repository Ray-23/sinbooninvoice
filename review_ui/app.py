from __future__ import annotations

import csv
import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from flask import Flask, redirect, render_template, request, url_for

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DATA_DIR = ROOT / "data"
INCOMING_DIR = DATA_DIR / "incoming"
APPROVED_DIR = DATA_DIR / "approved"
REJECTED_DIR = DATA_DIR / "rejected"
LOG_DIR = DATA_DIR / "logs"
for folder in (INCOMING_DIR, APPROVED_DIR, REJECTED_DIR, LOG_DIR):
    folder.mkdir(parents=True, exist_ok=True)

app = Flask(__name__)
app.secret_key = "order-bot-local-dev"

logger = logging.getLogger("orderbot.review")
if not logger.handlers:
    logger.setLevel(logging.INFO)
    file_handler = logging.FileHandler(LOG_DIR / "app.log")
    formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)


def read_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def pending_files() -> List[Path]:
    return sorted(INCOMING_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime)


def get_record(record_id: str) -> Optional[Dict[str, Any]]:
    path = INCOMING_DIR / f"{record_id}.json"
    if path.exists():
        return read_json(path)
    return None


def update_from_form(record: Dict[str, Any], form_data) -> Dict[str, Any]:
    customer = form_data.get("customer", "").strip() or None
    parse_result = record["parse_result"]
    raw_message = form_data.get("raw_message", parse_result.get("raw_message", ""))
    rows: List[Dict[str, Any]] = []
    row_count = int(form_data.get("row_count", 0))

    for idx in range(row_count):
        item = form_data.get(f"item_{idx}", "").strip()
        raw_line = form_data.get(f"raw_line_{idx}", "").strip()
        if not item and not raw_line:
            continue
        quantity_raw = form_data.get(f"quantity_{idx}", "").strip()
        price_raw = form_data.get(f"price_{idx}", "").strip()
        row = {
            "customer": customer,
            "item": item,
            "quantity": int(float(quantity_raw)) if quantity_raw and float(quantity_raw).is_integer() else (float(quantity_raw) if quantity_raw else None),
            "unit": form_data.get(f"unit_{idx}", "CTN").strip().upper() or "CTN",
            "weight": form_data.get(f"weight_{idx}", "").strip() or None,
            "price": float(price_raw) if price_raw else None,
            "raw_line": raw_line or item,
        }
        rows.append(row)

    parse_result["customer"] = customer
    parse_result["raw_message"] = raw_message
    parse_result["items"] = rows
    parse_result["status"] = "parsed" if rows else "needs_review"
    parse_result["stats"] = {
        "item_count": len(rows),
        "unparsed_count": 0,
    }
    record["parse_result"] = parse_result
    return record


def write_csv(path: Path, rows: List[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=["customer", "item", "quantity", "unit", "weight", "price", "raw_line"])
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def archive_raw_text(target_dir: Path, record: Dict[str, Any]) -> None:
    raw_dir = target_dir / "raw_messages"
    raw_dir.mkdir(parents=True, exist_ok=True)
    record_id = record["message_meta"]["record_id"]
    raw_text = record["parse_result"].get("raw_message", "")
    (raw_dir / f"{record_id}.txt").write_text(raw_text, encoding="utf-8")


def append_decision_log(record: Dict[str, Any], decision: str) -> None:
    path = LOG_DIR / "review_actions.csv"
    exists = path.exists()
    with path.open("a", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=["record_id", "decision", "customer", "item_count", "timestamp"],
        )
        if not exists:
            writer.writeheader()
        writer.writerow(
            {
                "record_id": record["message_meta"]["record_id"],
                "decision": decision,
                "customer": record["parse_result"].get("customer"),
                "item_count": len(record["parse_result"].get("items", [])),
                "timestamp": datetime.now().isoformat(timespec="seconds"),
            }
        )


@app.route("/")
def index():
    files = pending_files()
    queue = [read_json(path) for path in files]
    return render_template("index.html", queue=queue)


@app.route("/review/<record_id>", methods=["GET", "POST"])
def review(record_id: str):
    record = get_record(record_id)
    if not record:
        return redirect(url_for("index"))

    if request.method == "POST":
        action = request.form.get("action")
        record = update_from_form(record, request.form)
        src = INCOMING_DIR / f"{record_id}.json"

        if action == "save":
            write_json(src, record)
            logger.info("saved_review_draft record_id=%s", record_id)
            return redirect(url_for("review", record_id=record_id))

        if action == "approve":
            output_json = APPROVED_DIR / f"{record_id}.json"
            output_csv = APPROVED_DIR / f"{record_id}.csv"
            record["review_state"] = "approved"
            record["approved_at"] = datetime.now().isoformat(timespec="seconds")
            write_json(output_json, record)
            write_csv(output_csv, record["parse_result"].get("items", []))
            archive_raw_text(APPROVED_DIR, record)
            src.unlink(missing_ok=True)
            append_decision_log(record, "approved")
            logger.info("approved_order record_id=%s items=%s", record_id, len(record["parse_result"].get("items", [])))
            return redirect(url_for("index"))

        if action == "reject":
            record["review_state"] = "rejected"
            record["rejected_at"] = datetime.now().isoformat(timespec="seconds")
            output_json = REJECTED_DIR / f"{record_id}.json"
            write_json(output_json, record)
            archive_raw_text(REJECTED_DIR, record)
            src.unlink(missing_ok=True)
            append_decision_log(record, "rejected")
            logger.info("rejected_order record_id=%s", record_id)
            return redirect(url_for("index"))

    return render_template("review.html", record=record)


if __name__ == "__main__":
    app.run(debug=True, port=5001)
