# Global Business Travel Operations Agent

AI Agent Mini Project: a learning prototype for a mock-only agent supporting international business travel operations. The project uses bounded workflows, allowlisted function calling, policy evidence, draft-only artifacts, and evaluation traces. It must not perform real bookings, payments, refunds, or external communications.

## Project contents

- `docs/agent-design/` — architecture and contracts for the agent, tools, domain data, and workflow integration.
- `data/mock-systems/` — fictional source fixtures in CSV, JSON, and Markdown formats.
- `scripts/preprocess_to_sqlite.py` — standard-library preprocessing and SQLite seed pipeline.
- `data/processed/` — generated SQLite database and validation report (database is ignored by Git and can be regenerated).

## Prepare the local SQLite database

From the repository root, run:

```powershell
python scripts/preprocess_to_sqlite.py
```

Optional paths:

```powershell
python scripts/preprocess_to_sqlite.py --source data/mock-systems --output data/processed/travel_agent.sqlite
```

The script validates identifiers, required fields, dates, references, policy front matter/chunk metadata, and SQLite foreign keys. Invalid records are reported in `data/processed/validation_report.json`; source fixtures are not modified. Python standard library only is required.

## Data safety

All records and policy content are fictional training fixtures. Do not add real traveler PII, credentials, payment data, or production policy. The generated database is local output and is excluded from version control.
