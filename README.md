# Pramanik

Document verification for government officers (Hackathena project). An officer uploads a certificate (PDF, photo or scan);
Pramanik reads the printed fields and asks the **issuing department** whether they match its own record.
The issuer answers yes/no per field. It never hands its record back.

> **Status: Checkpoint 2.** One document type (income certificate), one simulated issuer. Accepts digital PDFs,
> photos, scans and image-only PDFs. See [What this does not do yet](#what-this-does-not-do-yet).

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

### Photos, scans and image-only PDFs

One upload box, one endpoint (`POST /verify`). The server tells PDF from image by the file's bytes. A photo or scan is
turned into the same inputs a PDF gives (document type, fields, QR text) and then judged by the same rules:

```
image -> quality gate -> find page + straighten -> find QR -> OCR (QR masked out) -> schema fields
                                                                    |
              same verdict rules, issuer lookup, field rows, audit as a PDF  <-+
```

- The **quality gate** judges paper level, ink contrast, sharpness and size, with limits in `config/scan.json`.
  A bad image is **RESCAN**, with advice on retaking it. Nothing is claimed about the document.
- Every value read by OCR has a **confidence**. If a field is missing, low-confidence, or two OCR passes disagree, the
  result is **INCONCLUSIVE** and the issuer is not asked. A shaky reading must never turn into an accusation.
- A PDF with no text layer (a "scan to PDF") is read the same way and reported as `scanned_pdf`.
- A photo's **MISMATCH**/**SUSPICIOUS** carries a reminder that the values were read from an image.

### Extra checks (apply to PDFs and photos; they can only refine a `VERIFIED` result)

| Check | Effect |
|---|---|
| **Issuer-signed QR** (Ed25519). A valid signature proves the QR came from the issuer. | A printed field that differs from the signed QR: **MISMATCH**. A QR whose signature fails: **MATCHES_RECORD_INTEGRITY_CONCERNS**. |
| **Visible-page check** (PDFs): the text layer is compared with an OCR reading of the rendered page. | A value that differs from what is shown: **MISMATCH**. Two different values for one field in the text layer: integrity concern. Defeats "paint over the number" and invisible-text forgeries. Switch off with `pdf_visual_check.enabled` in `scan.json`. |
| **Links** printed on the document (never fetched): `http`, shorteners, look-alike domains. | integrity concern / warning |
| **Reuse ledger**: the same certificate presented in other cases (fingerprints only, see Security notes). | warning, or integrity concern above a threshold |

Front-end developers: see [`backend/API.md`](backend/API.md) for the request and response contract.

### Risk score and issuer-answer cache

- **Risk score (0-100, with level low / medium / high).** A triage aid built from listed factors (verdict, each extra
  check that fired, OCR reliability, a valid signature lowering it). Every factor is shown with its points and reason
  (click the score in the result). It never changes a verdict. For RESCAN, INCONCLUSIVE and UNVERIFIABLE there is no score,
  because nothing was judged. Weights are in `config/risk.json`.
- **Cache.** The issuer's *answer* (found, status, per-field matches) is reused for `ttl_seconds` (default 10 minutes,
  `config/cache.json`) so repeated checks do not hit the department every time. The key is a keyed fingerprint of every
  extracted value, so an edited document can never be answered from a genuine one's entry. Never cached: "not found",
  outages, key problems, registries that disclose values. Entries carry an HMAC, so a tampered database cannot plant a
  "verified". Everything else (reuse, signature, image quality) is recomputed on each check. Tick **Ask the issuer again**
  to bypass it; the result shows `Issuer lookup: cache` or `live`. A certificate revoked inside the TTL window can still
  show as active until the entry expires or an officer asks again; lower `ttl_seconds` (or set `enabled` to false) if that matters more than speed.

Extra verdicts: **VERIFIED_WITH_WARNINGS** (matches, with points to review), **MATCHES_RECORD_INTEGRITY_CONCERNS** (matches
the record, but a check above failed: review before accepting), **RESCAN**, **INCONCLUSIVE**.

## Quick start

Requires Python 3.10+ and, for photos and scans, the **Tesseract** program
(Windows: <https://github.com/UB-Mannheim/tesseract/wiki>; `apt install tesseract-ocr`; `brew install tesseract`).
Without it everything else works and photos answer "reading photos is not available on this server"
(`GET /api/capabilities` shows what is available).

```bash
python -m venv venv && source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r backend/requirements.txt
python run_all.py                                      # first run: creates keys + demo documents, starts both services
```

Open <http://localhost:8001>. `python run_all.py --test` starts both services, generates the test PDFs and runs every test.

Manual start (two terminals), if you prefer:

```bash
python issuer_service/setup_keys.py                          # once: writes backend/.env and issuer_service/keys.json
cd issuer_service && uvicorn main:app --port 8002
cd backend && uvicorn app.main:app --port 8001
```

Keys are generated on your machine and never committed (`backend/.env`, `issuer_service/keys.json`,
`issuer_service/signing_keys/`, `backend/config/issuer_keys.json`). `--rotate` replaces the API keys.
QR **signing** keys are per machine too, so the demo documents (`demo_docs/pdfs`, `demo_docs/scans`) are generated, not
committed; `run_all.py` makes them when it makes keys. `--new-signing-key` adds a signing key and retires the old one
(certificates it signed still verify).

## Demos

The reuse ledger remembers every certificate and the cases it was checked in, so checking the *same* sample certificate
under several different case IDs correctly produces "already presented in other cases" warnings. To start a demo clean:
stop the backend, then `python backend/tools/reset_ledger.py --yes`.

## Tests

```bash
python -m unittest discover -s issuer_service/tests -v           # issuer + pipeline, no servers needed
python -m unittest discover -s backend/tests -p "test_*.py" -v   # photo stages, signed QR, links, ledger
python run_all.py --test                                          # everything, plus HTTP acceptance tests (fresh ledger)
```

## Where things live

| What | File |
|---|---|
| Document types: labels, value patterns, normalisation, match rules, key field, valid status | `backend/config/document_types.json` |
| Which issuer handles which type, its URL, key variable, timeout | `backend/config/issuers.json` |
| Page text, purposes, upload limit, verdict labels, sample results, every officer-facing message | `backend/config/ui.json` |
| The issuer's registries and whether it may disclose values | `issuer_service/registries.json` |
| The issuer's (mock) records | `issuer_service/data/mock_records.json` |
| Photo/scan thresholds, link allow-list, reuse limits | `backend/config/scan.json` |
| Risk score weights and levels | `backend/config/risk.json` |
| Issuer-answer cache on/off and lifetime | `backend/config/cache.json` |
| Test inputs | `backend/config/test_cases.json` |

A field with `ocr_repair: true` gets OCR letter/digit confusions (`O`/`0`, `I`/`1`) corrected when read from an image; never use it for names.
An optional `stamp_region: [x0, y0, x1, y1]` (fractions of the page) on a document type switches on the stamp-reuse check.

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
- **The reuse ledger** (`backend/data/pramanik.db`, SQLite by default; `DATABASE_URL` for PostgreSQL, which also holds the issuer-answer cache) stores only keyed
  HMAC fingerprints of the certificate and the case ID, never readable values, so a copy of the file reveals nothing.
  Rows are hash-chained so edits and deletions are detectable. Without `PRAMANIK_FINGERPRINT_KEY` the check is off
  (no guessable default). Run one backend process; the chain is protected within a process.
- **Signed QR**: the issuer's private key stays in `issuer_service/`; Pramanik holds only public keys. A valid signature
  proves a QR came from the issuer, not that a paper certificate is the one it was issued on.
- **OCR can misread.** Confidence gating and the two-pass cross-check make a shaky reading INCONCLUSIVE, but a
  confidently wrong reading is still possible; that is why image verdicts carry a reminder to rescan.
- **The QR check is a consistency check, not security.** It confirms the QR matches the printed number.
  Anyone forging a certificate can regenerate a matching QR. The issuer lookup is what verifies.
- "Verified" means the document matches the issuer's record, not that the declared facts (for example the income) are true.
- No secrets are committed. Rotate any credential that was ever committed, even in old history.

## What this does not do yet

- **Photos and scans are read by OCR**, so they are less reliable than a text PDF: no upside-down detection (phone EXIF
  rotation is handled), one printed layout, English only, flat or lightly warped pages.
- No tamper forensics (for example ELA heatmaps).
- The risk score is rule-based and hand-weighted, not learned from data; treat the weights as a starting point.
- No authority-side dashboard: the issuer logs outcomes but has no view for them.
- No officer login (see above) and no TLS between the services in this demo.
- Single document type and a single simulated issuer.

## Project layout

```
backend/            Pramanik backend (FastAPI) + page
  app/services/     verdict rules, shared flow (flow.py), PDF/QR extraction, signed-QR check, reuse ledger
  app/scan/         photo/scan front-end: quality, page finding, QR, OCR, field parsing
  app/checks/       signed-QR consistency, links, reuse (apply to PDFs and photos)
  config/           document types, issuers, scan thresholds, page text and messages, test inputs
  static/index.html the officer page (reads its settings from /api/ui-config)
  tests/            unit + HTTP acceptance tests      tools/  demo PDF and scan generators
issuer_service/     the simulated department: API-key auth, registries, field comparison, QR signing, its own data/
demo_docs/          generated sample certificates, PDFs and photos (made by run_all.py, not committed)
run_all.py          one-command start / test
```
