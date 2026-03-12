# Order Bot Prototype (MacBook Phase 1)

A low-cost local prototype for this pipeline:

**WhatsApp group -> parser -> review UI -> approved JSON/CSV**

This phase is intentionally limited to the MacBook prototype. It does **not** automate SQL Enterprise.

## Stack

- **WhatsApp listener:** Node.js + Baileys
- **Parser:** Python rule-based parser
- **Review UI:** Flask web app
- **Storage:** local JSON / CSV files
- **Logs:** local log files in `data/logs/`

## How to review this repo

### Project purpose

This repo is a MacBook prototype for capturing WhatsApp group orders, parsing them into structured order rows, and sending them through a local review UI before export.

### Folder structure

- `listener/`: live WhatsApp listener, QR auth session handling, and Node dependencies
- `parser/`: rule-based order parsing logic and parser test harness
- `review_ui/`: Flask review interface for pending orders
- `scripts/`: helper scripts for install, startup, demo ingest, and preflight checks
- `data/mappings/`: committed sample alias mappings used by the parser
- `data/incoming/`, `data/approved/`, `data/rejected/`, `data/logs/`: local generated runtime data, intentionally ignored by Git

### Startup commands

```bash
cd ~/order-bot
bash scripts/install_listener_mac.sh
cp .env.example .env
```

Set the exact WhatsApp group name in `.env`, then run:

```bash
cd ~/order-bot
./scripts/start_review_ui.sh
```

In a second terminal:

```bash
cd ~/order-bot
./scripts/start_listener.sh
```

### What is already working

- Python parser test mode
- demo ingest from sample text
- Flask review UI for pending messages
- local approve/reject flow with JSON and CSV output generation
- Mac helper scripts for install, preflight, review UI startup, and WhatsApp listener startup
- WhatsApp listener with QR login, target-group filtering, and ingestion into `data/incoming/`

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
    auth_info_baileys/        # created after first QR login
  parser/
    __init__.py
    order_parser.py
    test_parser.py
  review_ui/
    app.py
    templates/
      index.html
      review.html
  data/
    incoming/
    approved/
      raw_messages/
    rejected/
      raw_messages/
    logs/
    mappings/
      customers.json
      items.json
  scripts/
    ingest_message.py
    demo_ingest.sh
    sample_order.txt
  requirements.txt
  README.md
```

## What gets saved where

- **Pending incoming messages:** `data/incoming/*.json`
- **Approved order JSON:** `data/approved/*.json`
- **Approved order CSV:** `data/approved/*.csv`
- **Approved raw text archive:** `data/approved/raw_messages/*.txt`
- **Rejected records:** `data/rejected/*.json`
- **Rejected raw text archive:** `data/rejected/raw_messages/*.txt`
- **Runtime logs:** `data/logs/app.log`, `data/logs/listener.log`
- **Index logs:** `data/logs/incoming_index.csv`, `data/logs/review_actions.csv`
- **WhatsApp QR/session auth:** `listener/auth_info_baileys/`

## Setup

### 1) Python side

```bash
cd order-bot
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2) Node listener side

```bash
cd order-bot/listener
npm install
```

## Run commands

### Parser test mode

```bash
cd order-bot
python3 -m parser.test_parser
```

### Demo ingest (creates a pending review record from sample text)

```bash
cd order-bot
./scripts/demo_ingest.sh
```

### Review UI

```bash
cd order-bot
source .venv/bin/activate
python3 review_ui/app.py
```

Open:

```text
http://127.0.0.1:5001
```

### WhatsApp listener

```bash
cd order-bot/listener
TARGET_GROUP_NAME="YOUR GROUP NAME" npm start
```

On first run, scan the QR code shown in the terminal with WhatsApp on your phone.

## Parser rules implemented

- First meaningful line may be treated as the customer name
- Default unit is `CTN` if missing
- Supported units: `CTN`, `BAG`, `BOX`, `PKT`, `PCS`, `KG`, `JAR`
- Handles weights like `7kg` or `20kg`
- Handles prices like `$58`
- Ignores numbering like `1)` and `2)`
- Tolerates messy spacing and common WhatsApp formatting
- Saves `raw_line` for every parsed row

## Manual flow for this prototype

1. Start Flask review UI
2. Start WhatsApp listener with the exact target group name
3. Scan QR on first run
4. Incoming messages from that group are parsed and saved into `data/incoming/`
5. Open review UI, edit if needed, then approve or reject
6. Approved records produce JSON + CSV outputs

## What still needs to be done later on the Windows office PC

1. Replace the final approved-output step with SQL Enterprise automation
2. Add office-PC-specific Firebird / SQL workflow
3. Add production-grade item/customer alias tables from your real customer data
4. Add stronger duplicate detection and message threading
5. Add better handling for multi-message orders split across several WhatsApp posts
6. Add Windows service or scheduled startup for always-on runtime
7. Add backup / recovery handling for session and approved data

## Notes

- This is a **prototype** for proving the pipeline cheaply.
- Baileys auth is local to this machine in `listener/auth_info_baileys/`.
- For later migration, keep the parser and review UI logic mostly unchanged and replace only the final approved-output stage.
