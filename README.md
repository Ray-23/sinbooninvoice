# Order Bot Prototype (MacBook Phase 1)

A low-cost local prototype for this pipeline:

**WhatsApp order group + WhatsApp price group -> parser -> review UI -> approved JSON/CSV**

This phase is intentionally limited to the MacBook prototype. It does **not** automate SQL Enterprise.

## Stack

- **WhatsApp listener:** Node.js + Baileys
- **Order parser:** Python rule-based parser
- **Price parser:** Python rule-based parser
- **Review UI:** Flask web app
- **Storage:** local JSON / CSV files
- **Logs:** local log files in `data/logs/`

## How to review this repo

### Project purpose

This repo captures order messages from the `SinboonInvoice` WhatsApp group, captures price-list messages from the `SinboonPrice` WhatsApp group, parses both locally, and lets an operator review orders with the latest price reference visible on each row before approval or rejection.

### Folder structure

- `listener/`: live WhatsApp listener, QR auth session handling, and Node dependencies
- `parser/`: order parsing, price parsing, and parser test harnesses
- `review_ui/`: Flask review interface for pending orders and history panels
- `scripts/`: install, startup, preflight, and demo fixtures for the MacBook flow
- `data/mappings/`: committed sample alias mappings used by the parser
- `data/incoming/`, `data/approved/`, `data/rejected/`, `data/logs/`, `data/prices/`: local generated runtime data, intentionally ignored by Git

### Startup commands

```bash
cd ~/order-bot
bash scripts/install_listener_mac.sh
cp .env.example .env
```

Set the group names in `.env`, then use the one-terminal startup:

```bash
cd ~/order-bot
./scripts/start_all_mac.sh
```

That starts Flask in the background, waits for `http://127.0.0.1:5001`, opens Google Chrome, and keeps the WhatsApp listener in the foreground so the QR code remains visible.

### What is already working

- dual-group WhatsApp listener for orders and price messages
- QR login with local Baileys auth state
- order parsing into pending review records
- price parsing into raw history snapshots and a latest price catalog
- automatic order-row reference pricing from `data/prices/latest_prices.json`
- Flask review UI with pending queue plus latest 10 approved and rejected panels
- local approve/reject flow with JSON, CSV, and raw-message archive output
- Mac helper scripts for install, preflight, listener startup, review UI startup, and all-in-one startup

### What is not yet implemented

- SQL Enterprise or Windows office-PC automation
- production-grade customer and item alias data
- stronger duplicate detection and multi-message order stitching
- Windows startup/service handling
- backup and recovery workflow for long-running production use

## Folder structure

```text
order-bot/
  listener/
    index.mjs
    package.json
    auth_info_baileys/        # created after first QR login, ignored by git
  parser/
    __init__.py
    order_parser.py
    price_parser.py
    test_parser.py
    test_price_parser.py
  review_ui/
    app.py
    templates/
      index.html
      review.html
  data/
    incoming/                 # ignored by git
    approved/                 # ignored by git
      raw_messages/
    rejected/                 # ignored by git
      raw_messages/
    prices/                   # ignored by git
      raw/
      history/
      latest_prices.json
    logs/                     # ignored by git
    mappings/
      customers.json
      items.json
  scripts/
    ingest_message.py
    install_listener_mac.sh
    preflight_listener_mac.sh
    start_listener.sh
    start_review_ui.sh
    start_all_mac.sh
    sample_order.txt
    sample_price_message.txt
  requirements.txt
  README.md
```

## Environment configuration

Preferred keys:

```bash
ORDER_GROUP_NAME="SinboonInvoice"
PRICE_GROUP_NAME="SinboonPrice"
```

Backward compatibility:

```bash
TARGET_GROUP_NAME="SinboonInvoice"
```

`ORDER_GROUP_NAME` takes precedence over `TARGET_GROUP_NAME` if both are present.

## What gets saved where

- **Pending incoming orders:** `data/incoming/*.json`
- **Approved order JSON:** `data/approved/*.json`
- **Approved order CSV:** `data/approved/*.csv`
- **Approved raw text archive:** `data/approved/raw_messages/*.txt`
- **Rejected records:** `data/rejected/*.json`
- **Rejected raw text archive:** `data/rejected/raw_messages/*.txt`
- **Price raw message archive:** `data/prices/raw/*.txt`
- **Price parsed history snapshots:** `data/prices/history/*.json`
- **Latest price catalog:** `data/prices/latest_prices.json`
- **Runtime logs:** `data/logs/app.log`, `data/logs/listener.log`
- **Index logs:** `data/logs/incoming_index.csv`, `data/logs/review_actions.csv`
- **WhatsApp QR/session auth:** `listener/auth_info_baileys/`

## Setup

### 1) Python side

```bash
cd ~/order-bot
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2) Node listener side

```bash
cd ~/order-bot/listener
npm install
```

### 3) Quick install helper

```bash
cd ~/order-bot
bash scripts/install_listener_mac.sh
```

## Run commands

### Order parser test mode

```bash
cd ~/order-bot
python3 -m parser.test_parser
```

### Price parser test mode

```bash
cd ~/order-bot
python3 -m parser.test_price_parser
```

### Review UI only

```bash
cd ~/order-bot
./scripts/start_review_ui.sh
```

Open:

```text
http://127.0.0.1:5001
```

### WhatsApp listener only

```bash
cd ~/order-bot
./scripts/start_listener.sh
```

### One-terminal startup

```bash
cd ~/order-bot
./scripts/start_all_mac.sh
```

On first run, scan the QR code shown in the terminal with WhatsApp on your phone.

## Price reference rules

- Price messages are read from `SinboonPrice`
- The first line must start with a date such as `6/3china container arrival`
- The effective price date is parsed as **DD/MM/current-year** unless the year is explicitly present
- Product lines default to **CTN** unless the line explicitly says `/pkt`, `/kg`, `/pcs`, or another supported basis
- Raw price text is preserved for audit in `data/prices/raw/`
- Parsed history is preserved in `data/prices/history/`
- `data/prices/latest_prices.json` is replaced only when the incoming price message has:
  1. a newer effective price date, or
  2. the same effective price date but a later received timestamp

## Manual flow for this prototype

1. Start everything with `./scripts/start_all_mac.sh`
2. Scan QR on first run
3. Price messages from `SinboonPrice` update `data/prices/latest_prices.json`
4. Order messages from `SinboonInvoice` are parsed into `data/incoming/`
5. Open the review UI, inspect the reference prices beside each item row, then save, approve, or reject
6. Approved records produce JSON + CSV outputs and rejected records are archived separately

## Notes

- This is a **prototype** for proving the pipeline cheaply.
- Baileys auth is local to this machine in `listener/auth_info_baileys/` and is ignored by Git.
- Runtime data under `data/` is local-only and ignored by Git.
- For later migration, keep the parser and review UI logic mostly unchanged and replace only the final approved-output stage.
