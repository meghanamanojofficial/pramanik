# Pramanik backend API

Same origin as the pages (`http://localhost:8001`); the browser sends the session cookie automatically. For a separate
dev server, either proxy it to the backend or list its address in `PRAMANIK_CORS_ORIGINS` (explicit origins only) and use
`fetch(..., { credentials: 'include' })`.

All `/api/*` and `/verify` responses are `Cache-Control: no-store`. Errors are `{"detail": "<message to show>"}`.
State-changing requests that carry an `Origin` of another site are refused (403).

## Accounts (`/api/auth/*`, JSON)

| Request | Body | Success | Errors |
|---|---|---|---|
| `GET /api/auth/options` | | `{signup: "open"\|"code"\|"closed", roles: [...]}` | |
| `POST /api/auth/signup` | `{email, password, signup_code?}` | `{user}` + session cookie | 400 invalid e-mail / password length (8-128); 403 closed / wrong code; 409 e-mail taken; 429 too many |
| `POST /api/auth/login` | `{email, password}` | `{user}` + session cookie | 401 wrong e-mail or password (same message for both); 429 too many attempts |
| `POST /api/auth/logout` | | `{ok: true}`, cookie cleared, session ended on the server | |
| `GET /api/auth/me` | | `{user}` | 401 |
| `PUT /api/auth/profile` | `{full_name, officer_id, phone?, organisation?, role?}` | `{user}` | 400 invalid; 401; 409 officer ID belongs to another account |

`user` = `{email, full_name, phone, organisation, role, officer_id, profile_complete}`. Officer IDs are 2-63 characters of
letters, digits and `. _ - /`, unique per account. `role` is one of `Citizen, Officer, Employer, Institution`
(informational; it grants nothing).

## `POST /verify`  (multipart form; needs a signed-in user with a complete profile: 401 / 403 otherwise)

| Field | Required | Notes |
|---|---|---|
| `file` | yes | A PDF, or a JPG / PNG / WebP photo or scan. The type is read from the bytes, not the name. Max size: `max_upload_mb` in `/api/ui-config`. |
| `case_id` | yes | The case or application. Never written to the audit log; used (as a keyed fingerprint) to tell reuse across cases from re-checking within one. |
| `purpose` | no | Accepted, deliberately not stored. |
| `fresh` | no | `1` = ask the issuer again instead of reusing its answer from the last few minutes. |
| `officer_id` | no | Ignored. The officer is the signed-in account. |

Errors: 400 (no case id, unsupported or unreadable file), 401, 403 (profile incomplete), 413 (too large), 500 (generic).

### Result (200)

```jsonc
{
  "verdict": "VERIFIED",              // see the table; show verdict_labels from /api/ui-config, not the raw code
  "route": "direct_issuer",           // or "none" when the issuer was not asked
  "input_type": "pdf",                // "pdf" | "scan" (photo/scan) | "scanned_pdf" (image-only PDF read by OCR)
  "document_type": "income_certificate",   // null if not recognised
  "document_title": "Income Certificate",  // null if not recognised
  "issuer": { "id": "revenue_dept", "name": "Revenue Department" },   // null if the type was not recognised
  "coverage": "4 of 4 printed fields confirmed with issuer",
  "reasons": ["All printed fields match the issuer record."],         // show these to the officer
  "fields": [                         // [] when nothing could be compared (RESCAN, INCONCLUSIVE ...)
    { "field": "income_amount", "label": "Annual income", "document": "100000",
      "issuer": "100000",             // or "does not match" / "not found" / "unavailable" ...
      "match": true,
      "confidence": 96 }              // photos/scans only: OCR confidence 0-100 for the value
  ],
  "checks": { "qr_consistency": "pass", "digital_signature": "valid", "issuer_lookup": "live", "reuse_check": "pass" },
  "risk": { "score": 0, "level": "low",   // low | medium | high | not_assessed (score is null then)
            "factors": [{ "name": "valid_signature", "points": -10, "detail": "..." }] },
  "signals": [{ "name": "...", "severity": "ok|weak|strong|fail", "detail": "...", "region": null }],
  "rescan_guidance": null,            // text to show for RESCAN and INCONCLUSIVE
  "audit": { "doc_hash": "...", "officer_id": "...", "officer_id_source": "authenticated_account", "timestamp": "..." }
}
```

Values inside the result (names, reasons built from the document, link text) come from the uploaded file: **render them as
text, never as HTML.**

### Verdicts

| `verdict` | Meaning | Suggested colour |
|---|---|---|
| `VERIFIED` | Every field matches an active issuer record. | green |
| `VERIFIED_WITH_WARNINGS` | Matches, with points to review (see `signals`). | yellow |
| `MATCHES_RECORD_INTEGRITY_CONCERNS` | Matches the record, but another check failed (forged QR signature, suspicious link, certificate reused in many cases). | orange |
| `MISMATCH` | A field differs from the record, or the document contradicts its own signed QR or what the page shows. Neutral wording on purpose: it can be an edit or a clerical error. | red |
| `SUSPICIOUS` | No such certificate, revoked or expired, or the QR number differs from the printed one. | amber |
| `UNVERIFIABLE` | Could not decide (unknown type, issuer unreachable, OCR not installed). `reasons` says why. | grey |
| `RESCAN` | Photo or scan not good enough to read. Show `rescan_guidance`. Nothing was claimed about the document. | blue |
| `INCONCLUSIVE` | Read, but not reliably. Show `rescan_guidance`. | grey |

Treat unknown verdict values as "show the label and the reasons": more may be added.

## `GET /api/history?limit=20` (signed in)

This account's recent checks, newest first, from the audit log: `[{verdict, route, input_type, doc_hash, officer_id, timestamp}]`.
There are no file names or document contents (the audit log does not keep them); the pages remember names for the current
browser session only.

## Other endpoints

- `GET /api/ui-config` (public): app title, purposes, `max_upload_mb`, `accept` (MIME types), `verdict_labels`, `risk_labels`,
  `document_types` (`[{id, title, issuer}]`, what is actually supported), `issuers` (names), `samples`.
- `GET /api/capabilities` (public): `{pdf, ocr, reuse_ledger, qr_signature_keys}`; useful when photos report "not available".
- `GET /health` (public): `{status, records_loaded}`.
- `GET /app/<page>.html` (the pages; signed-out visitors are redirected to sign-in), `GET /classic` (plain fallback page).

## What changed since the first version

- `/verify` needs a login; the officer comes from the account, not the form. New `/api/auth/*` and `/api/history`.
- Also accepts images (one endpoint). New verdicts: `VERIFIED_WITH_WARNINGS`, `MATCHES_RECORD_INTEGRITY_CONCERNS`,
  `RESCAN`, `INCONCLUSIVE`.
- New response fields: `document_title`, `issuer`, `risk`, `signals`, `rescan_guidance`, `fields[].confidence`,
  `checks.issuer_lookup`, `checks.reuse_check`; `input_type` can be `scan` / `scanned_pdf`; `checks.digital_signature` can be
  `valid` / `invalid`. New request field: `fresh`. Existing fields keep their names and meaning.
