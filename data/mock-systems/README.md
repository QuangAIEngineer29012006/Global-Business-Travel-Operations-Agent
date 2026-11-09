# Mock Systems and Dataset

Training-only fixtures for the Global Business Travel Operations Agent. All people, companies, policy text, amounts, itineraries, and events are invented. No external service or real booking is represented.

## Contents and formats

- `travel-requests/travel_requests.csv` — 6 trip records.
- `traveler-profiles/traveler_profiles.json` — 4 profiles across 4 departments; non-sensitive preferences only.
- `itineraries/itineraries.json` — 4 nested itinerary records; 2 disruption cases (delay and cancellation).
- `approvals/approvals.csv` — pending, approved, rejected trip decisions plus pending expense review simulation.
- `expenses/expense_reports.json` — 3 reports with valid, missing receipt, and reviewer-threshold scenarios.
- `policy-knowledge-base/documents/*.md` — 4 fictional source documents containing 9 chunks across travel, expense, visa, insurance, and approval.
- `policy-knowledge-base/chunk_metadata.csv` — retrieval/citation index; retain metadata through response generation.
- `draft-workspace/drafts.json` — empty sandbox draft store.

## Fixture map

| Scenario | Fixture IDs | Intended branch |
|---|---|---|
| Pre-trip awaiting approval | TRIP-2026-001 / APR-2026-001 | Do not claim approved; checklist draft or awaiting approval |
| In-trip delay | TRIP-2026-002 / ITIN-002 | Support/escalation draft, no rebooking |
| Expense valid | EXP-2026-001 | Deterministic summary; receipt complete |
| Expense missing receipt | EXP-2026-002 | Flag for reviewer |
| Expense above mock threshold | EXP-2026-003 | Flag for reviewer; no reimbursement decision |
| Missing required cost center | TRIP-2026-004 | Ask for input |
| Rejected/cancelled trip | TRIP-2026-005 / TRIP-2026-006 | Respect terminal source status |
| In-trip cancellation | TRIP-2026-003 / ITIN-003 | Escalation draft; no rebooking |

## Data relationships

`trip_requests.traveler_id` references traveler profiles. Each itinerary references a trip. Expense reports reference trip and traveler. Approval rows reference trip or report. Policy chunk IDs are unique and map to the CSV metadata index.

## Ingestion notes

- Parse CSV as UTF-8; parse JSON as UTF-8 JSON arrays/objects.
- Markdown YAML front matter identifies each document; chunk headings identify the chunk and section. Preserve `doc_id`, `source`, `version`, `category`, `chunk_id` and section when indexing.
- One JSON file may contain an array at its top level. IDs are mock identifiers only.
- The expense threshold in policy is fictional and is included only to exercise retrieval and reviewer flags.

## Known limitations

No country-specific visa advice, live travel data, real policy, currency conversion, insurance coverage determination, production credentials, or personally identifying data is included. These documents are not authoritative policy.
