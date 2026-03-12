from __future__ import annotations

import json
from pathlib import Path

from parser.order_parser import parse_message

SAMPLE_MESSAGES = [
    """Ming Star..
Broccoli 7kg 1 CTN
Celery 12kg 1 CTN
Durian Sweet Potato 1 CTN
Lotus Root 10kg 1 CTN
Sweet cabbage 20kg 4 BAG""",
    """1) Soon Lee
2) Tomato 10kg 2 ctn
3) Long Bean 1 bag $58
4) garlic 5 pkt""",
    """Ah Hock
Baby kailan 7kg
Beetroot 1 BOX
Pumpkin $22 1 CTN""",
]


def main() -> None:
    out_dir = Path(__file__).resolve().parents[1] / "data" / "logs"
    out_dir.mkdir(parents=True, exist_ok=True)

    results = [parse_message(msg) for msg in SAMPLE_MESSAGES]
    output_path = out_dir / "parser_test_output.json"
    output_path.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(results, indent=2, ensure_ascii=False))
    print(f"\nSaved parser test output to: {output_path}")


if __name__ == "__main__":
    main()
