# Pramanik

Document verification for government officers (Hackathena project). An officer uploads a certificate PDF;
Pramanik reads the printed fields and asks the **issuing department** whether they match its own record.
The issuer answers yes/no per field. It never hands its record back.

> **Status: Checkpoint 1.** One document type (income certificate), text-based PDFs only, one simulated issuer.
> See [What this does not do yet](#what-this-does-not-do-yet).

## How it works

```
Officer browser ──► Pramanik backend :8001 ──(HTTP + X-API-Key)──► Issuer service :8002 ──► issuer's records
                    read PDF, detect type,                          check key, look up the key field,
                    extract fields, QR check,                       compare each field by its rule,
                    verdict, audit line                             answer found / status / per-field match
```

1. Pramanik detects the document type and extracts its fields (all defined in `backend/config/document_types.json`).
2. It sends only those fields to the issuer that handles that type (`backend/config/issuers.json`).
3. The issuer replies `found`, `status` and a per-field `matches` map. Its own values are not disclosed
   (unless a registry sets `"disclose_values": true`, a demo-only switch).
4. Pramanik turns that into a verdict:

| Verdict | Meaning |
|---|---|
| **VERIFIED** | Every printed field matches an active issuer record. |
| **MISMATCH** ("Does not match issuer record") | The record exists but one or more fields differ. This can be an edit, but also a clerical error or registry lag, so the wording is deliberately neutral. |
| **SUSPICIOUS** | No such certificate number, the QR disagrees with the printed number, or the record is revoked/expired. |
| **UNVERIFIABLE** | Could not decide: unreadable document, unknown type, or the issuer could not answer. The reason says which (unreachable, key rejected, key not configured, rate limited, registry unavailable, insecure address). |

## Quick start

Requires Python 3.10+.

```bash
python -m venv venv && source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r backend/requirements.txt
python run_all.py                                      # creates API keys on first run, starts both services
```

Open <http://localhost:8001>. `python run_all.py --test` starts both services, generates the test PDFs and runs every test.

Manual start (two terminals), if you prefer:

```bash
python issuer_service/setup_keys.py                          # once: writes backend/.env and issuer_service/keys.json
cd issuer_service && uvicorn main:app --port 8002
cd backend && uvicorn app.main:app --port 8001
```

Keys are generated on your machine and never committed (`backend/.env`, `issuer_service/keys.json`).
`--rotate` replaces them: `python issuer_service/setup_keys.py --rotate`.

## Tests

```bash
python -m unittest discover -s issuer_service/tests -v     # issuer + pipeline, no servers needed
python run_all.py --test                                    # also runs the HTTP acceptance tests
```

## Where things live

| What | File |
|---|---|
| Document types: labels, value patterns, normalisation, match rules, key field, valid status | `backend/config/document_types.json` |
| Which issuer handles which type, its URL, key variable, timeout | `backend/config/issuers.json` |
| Page text, purposes, upload limit, verdict labels, sample results, every officer-facing message | `backend/config/ui.json` |
| The issuer's registries and whether it may disclose values | `issuer_service/registries.json` |
| The issuer's (mock) records | `issuer_service/data/mock_records.json` |
| Test inputs | `backend/config/test_cases.json` |

Match rules per field (`compare.method`): `exact` (default), `name` (ignores case, spacing, punctuation and word
order, but any changed letter is a mismatch), `fuzzy` (looser; avoid for identity fields).
Adding a document type is a JSON change, not a code change.

## Issuer API (what a real department would implement)

Both endpoints need an `X-API-Key` header. Keys are random, stored only as SHA-256 hashes, scoped to one issuer,
rate limited, and revocable.

- `POST /v1/verify` with `{"document_type": "...", "fields": {"certificate_number": "...", ...}}`
  returns `{"issuer_id", "found", "status", "matches": {"<field>": true|false}}`.
  Status codes: 401 bad key, 403 key not allowed for this issuer, 404 no registry for the type, 429 rate limited,
  503 registry unavailable.
- `GET /v1/stats` returns `{"records_loaded": N}` (used by Pramanik's `/health`).

The issuer's audit log (`issuer_service/audit.jsonl`) records key, issuer and outcome only: no names, numbers or amounts.

## Security notes

- **Officer ID is self-reported.** There is no login yet, so the audit log's `officer_id` is typed into the form and
  every audit line is marked `"officer_id_source": "self_reported"`. The log shows what was checked and when. It is not
  proof of who checked it. Real accountability needs authentication (for example SSO).
- **Transport.** Pramanik refuses to send the API key over plain HTTP to anything except localhost.
  In production the issuer link needs HTTPS (ideally mutual TLS).
- **Uploads stay in memory** and are limited by `max_upload_mb` in `ui.json`. The audit log stores a SHA-256 of the file,
  not its content, and never names, fields or case IDs.
- **The QR check is a consistency check, not security.** It confirms the QR matches the printed number.
  Anyone forging a certificate can regenerate a matching QR. The issuer lookup is what verifies.
- "Verified" means the document matches the issuer's record, not that the declared facts (for example the income) are true.
- No secrets are committed. Rotate any credential that was ever committed, even in old history.

## What this does not do yet

- Reads **text-based PDFs only**. Scans and phone photos need OCR.
- No tamper forensics (for example ELA heatmaps), no risk score, no cache of "already verified" results.
- No authority-side dashboard: the issuer logs outcomes but has no view for them.
- No officer login (see above) and no TLS between the services in this demo.
- Single document type and a single simulated issuer.

## Project layout

```
backend/            Pramanik backend (FastAPI) + page
  app/              routes, issuer client, verdict rules, PDF/QR extraction
  config/           document types, issuers, page text and messages, test inputs
  static/index.html the officer page (reads its settings from /api/ui-config)
  tests/            HTTP acceptance tests      tools/  test-PDF generator
issuer_service/     the simulated department: API-key auth, registries, field comparison, its own data/
demo_docs/          generated sample certificates
run_all.py          one-command start / test
```
