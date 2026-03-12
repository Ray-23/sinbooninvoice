from __future__ import annotations

import json
import re
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

BASE_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = BASE_DIR / "data"
MAPPINGS_DIR = DATA_DIR / "mappings"
VALID_UNITS = {"CTN", "BAG", "BOX", "PKT", "PCS", "KG", "JAR"}
CUSTOMER_STOPWORDS = {
    "please",
    "thanks",
    "thank you",
    "urgent",
    "delivery",
    "send",
    "today",
    "tomorrow",
    "bro",
    "boss",
}

NUMBERING_RE = re.compile(r"^\s*(?:[-*•]+|\d+\s*[\).:-])\s*")
WEIGHT_RE = re.compile(r"\b(\d+(?:\.\d+)?)\s*(kg)\b", re.IGNORECASE)
PRICE_RE = re.compile(r"(?:\$|rm\s*)(\d+(?:\.\d{1,2})?)\b", re.IGNORECASE)
QTY_UNIT_RE = re.compile(r"\b(\d+(?:\.\d+)?)\s*(CTN|BAG|BOX|PKT|PCS|KG|JAR)\b", re.IGNORECASE)
QTY_AFTER_UNIT_RE = re.compile(r"\b(CTN|BAG|BOX|PKT|PCS|KG|JAR)\s*(\d+(?:\.\d+)?)\b", re.IGNORECASE)
INLINE_COUNT_RE = re.compile(r"\b(?:x|qty\s*:?\s*)(\d+(?:\.\d+)?)\b", re.IGNORECASE)
PURE_QTY_RE = re.compile(r"\b(\d+(?:\.\d+)?)\b")


@dataclass
class ParsedLine:
    customer: Optional[str]
    item: str
    quantity: Optional[float]
    unit: str
    weight: Optional[str]
    price: Optional[float]
    raw_line: str

    def as_output(self) -> Dict[str, Any]:
        data = asdict(self)
        qty = data["quantity"]
        if isinstance(qty, float) and qty.is_integer():
            data["quantity"] = int(qty)
        return data


def _load_json_file(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def load_mappings() -> Tuple[Dict[str, str], Dict[str, str]]:
    customers = _load_json_file(MAPPINGS_DIR / "customers.json").get("aliases", {})
    items = _load_json_file(MAPPINGS_DIR / "items.json").get("aliases", {})
    return (
        {str(k).strip().lower(): str(v).strip() for k, v in customers.items()},
        {str(k).strip().lower(): str(v).strip() for k, v in items.items()},
    )


def normalize_alias(value: Optional[str], mapping: Dict[str, str]) -> Optional[str]:
    if value is None:
        return None
    stripped = re.sub(r"\s+", " ", value).strip(" .,:;\t\n\r")
    return mapping.get(stripped.lower(), stripped)


def clean_customer_name(raw: str) -> str:
    cleaned = NUMBERING_RE.sub("", raw or "")
    cleaned = re.sub(r"[._]{2,}$", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .,:;\t\n\r")
    return cleaned


def clean_item_name(raw: str) -> str:
    cleaned = NUMBERING_RE.sub("", raw)
    cleaned = re.sub(r"\s+", " ", cleaned)
    cleaned = cleaned.strip(" .,:;\t\n\r-")
    cleaned = re.sub(r"\bctn\b|\bbag\b|\bbox\b|\bpkt\b|\bpcs\b|\bkg\b|\bjar\b", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .,:;\t\n\r-")
    return cleaned


def strip_known_tokens(line: str) -> Tuple[str, Optional[str], Optional[float], Optional[float], Optional[str]]:
    working = NUMBERING_RE.sub("", line)

    price = None
    price_match = PRICE_RE.search(working)
    if price_match:
        price = float(price_match.group(1))
        working = PRICE_RE.sub(" ", working, count=1)

    weight = None
    weight_match = WEIGHT_RE.search(working)
    if weight_match:
        weight = f"{weight_match.group(1)}kg"
        working = WEIGHT_RE.sub(" ", working, count=1)

    quantity = None
    unit = None

    qty_unit_match = None
    qty_unit_matches = list(QTY_UNIT_RE.finditer(working))
    if qty_unit_matches:
        qty_unit_match = qty_unit_matches[-1]
        quantity = float(qty_unit_match.group(1))
        unit = qty_unit_match.group(2).upper()
        working = working[:qty_unit_match.start()] + " " + working[qty_unit_match.end():]
    else:
        unit_qty_match = QTY_AFTER_UNIT_RE.search(working)
        if unit_qty_match:
            unit = unit_qty_match.group(1).upper()
            quantity = float(unit_qty_match.group(2))
            working = QTY_AFTER_UNIT_RE.sub(" ", working, count=1)
        else:
            inline_match = INLINE_COUNT_RE.search(working)
            if inline_match:
                quantity = float(inline_match.group(1))
                working = INLINE_COUNT_RE.sub(" ", working, count=1)

    if quantity is None:
        numbers = [m for m in PURE_QTY_RE.finditer(working)]
        if numbers:
            quantity = float(numbers[-1].group(1))
            working = working[:numbers[-1].start()] + " " + working[numbers[-1].end():]

    if unit is None:
        unit = "CTN"

    return working, weight, quantity, price, unit


def looks_like_customer(line: str) -> bool:
    stripped = clean_customer_name(line)
    if not stripped:
        return False
    lowered = stripped.lower()
    if any(word in lowered for word in CUSTOMER_STOPWORDS):
        return False
    if PRICE_RE.search(stripped):
        return False
    if QTY_UNIT_RE.search(stripped) or QTY_AFTER_UNIT_RE.search(stripped):
        return False
    if WEIGHT_RE.search(stripped):
        return False
    digit_count = sum(ch.isdigit() for ch in stripped)
    if digit_count > 0:
        return False
    words = stripped.split()
    return 1 <= len(words) <= 5


def parse_order_line(line: str, customer: Optional[str] = None, item_aliases: Optional[Dict[str, str]] = None) -> Optional[Dict[str, Any]]:
    raw_line = re.sub(r"\s+", " ", line).strip()
    if not raw_line:
        return None

    working, weight, quantity, price, detected_unit = strip_known_tokens(raw_line)
    item = clean_item_name(working)

    if not item:
        return None

    if item_aliases:
        item = normalize_alias(item, item_aliases) or item

    parsed = ParsedLine(
        customer=customer,
        item=item,
        quantity=quantity,
        unit=(detected_unit or ("CTN" if not quantity else strip_unit_default(raw_line))),
        weight=weight,
        price=price,
        raw_line=raw_line,
    )

    if parsed.quantity is None:
        parsed.quantity = 1

    if parsed.unit not in VALID_UNITS:
        parsed.unit = "CTN"

    return parsed.as_output()


def strip_unit_default(raw_line: str) -> str:
    matches = list(QTY_UNIT_RE.finditer(raw_line))
    if matches:
        unit = matches[-1].group(2).upper()
        return unit if unit in VALID_UNITS else "CTN"
    m = QTY_AFTER_UNIT_RE.search(raw_line)
    if m:
        unit = m.group(1).upper()
        return unit if unit in VALID_UNITS else "CTN"
    working = WEIGHT_RE.sub(" ", raw_line)
    working = PRICE_RE.sub(" ", working)
    standalone = re.search(r"\b(CTN|BAG|BOX|PKT|PCS|KG|JAR)\b", working, re.IGNORECASE)
    if standalone:
        unit = standalone.group(1).upper()
        return unit if unit in VALID_UNITS else "CTN"
    return "CTN"


def parse_message(raw_message: str) -> Dict[str, Any]:
    customer_aliases, item_aliases = load_mappings()
    lines = [re.sub(r"\s+", " ", line).strip() for line in (raw_message or "").splitlines()]
    meaningful = [line for line in lines if line]
    customer = None
    order_lines = meaningful[:]

    if meaningful and looks_like_customer(meaningful[0]):
        customer = normalize_alias(clean_customer_name(meaningful[0]), customer_aliases)
        order_lines = meaningful[1:]

    items: List[Dict[str, Any]] = []
    unparsed: List[str] = []

    for line in order_lines:
        maybe_customer = looks_like_customer(line) and not re.search(r"\b\d+\b", line)
        if customer is None and maybe_customer:
            customer = normalize_alias(clean_customer_name(line), customer_aliases)
            continue
        parsed = parse_order_line(line, customer=customer, item_aliases=item_aliases)
        if parsed:
            parsed["customer"] = customer
            items.append(parsed)
        else:
            unparsed.append(line)

    return {
        "customer": customer,
        "items": items,
        "raw_message": raw_message,
        "unparsed_lines": unparsed,
        "status": "parsed" if items else "needs_review",
        "stats": {
            "item_count": len(items),
            "unparsed_count": len(unparsed),
        },
    }
