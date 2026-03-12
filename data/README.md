# Data directories

This repository only tracks the alias mapping files in `data/mappings/`.

The following directories are generated locally at runtime and are intentionally ignored by Git:

- `data/incoming/`
- `data/approved/`
- `data/rejected/`
- `data/logs/`

These folders will be created and used by the parser, review UI, and WhatsApp listener on the operator's machine.
