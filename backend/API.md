# Pramanik backend API (for front-end developers)

Base URL `http://localhost:8001`. If your front end runs on a different address (for example a Vite dev server on
`:5173`), add that origin to `backend/.env`: `PRAMANIK_CORS_ORIGINS=http://localhost:5173` and restart. (Or use your
dev server's proxy, which needs no setting.)

## `POST /verify`  (multipart form)

| Field | Required | Notes |
|---|---|---|
| `file` | yes | A PDF, or a JPG / PNG / WebP photo or scan. Type is detected from the bytes, not the name. Max size is `max_upload_mb` in `/api/ui-config`. |
| `case_id` | yes | Case or application ID. Never written to the audit log. |
| `officer_id` | no | Self-reported; logged as such. |
| `purpose` | no | Accepted, deliberately not stored. |
| `fresh` | no | `1` = ask the issuer again instead of reusing its recent answer (the cache). |

Errors are `{"detail": "<message>"}` with status 400 (no case id, unsupported or unreadable file), 413 (too large), 500.

### Success response (200)

```jsonc
{
  "verdict": "VERIFIED",              // see the table below; show verdict_labels from /api/ui-config, not the raw code
  "route": "direct_issuer",           // or "none" when the issuer was not asked
  "input_type": "pdf",                // "pdf" | "scan" (photo/scan) | "scanned_pdf" (image-only PDF read by OCR)
  "document_type": "income_certificate",   // null if not recognised
  "coverage": "4 of 4 printed fields confirmed with issuer",
  "reasons": ["All printed fields match the issuer record."],   // show these to the officer
  "fields": [                         // [] when nothing could be compared (RESCAN, INCONCLUSIVE ...)
    { "field": "income_amount", "label": "Annual income", "document": "100000",
      "issuer": "100000",             // or "does not match" / "not found" / "unavailable" ...
      "match": true,
      "confidence": 96 }              // only for photos/scans: OCR confidence 0-100 for the value
  ],
  "checks": { "qr_consistency": "pass", "digital_signature": "valid", "issuer_lookup": "live", "reuse_check": "pass" },
  "risk": { "score": 0, "level": "low",   // level: low | medium | high | not_assessed (score is null then)
            "factors": [{ "name": "valid_signature", "points": -10, "detail": "..." }] },
  "signals": [{ "name": "...", "severity": "ok|weak|strong|fail", "detail": "...", "region": null }],
  "rescan_guidance": null,            // text to show when the verdict is RESCAN or INCONCLUSIVE
  "audit": { "doc_hash": "...", "officer_id": "...", "officer_id_source": "self_reported", "timestamp": "..." }
}
```

### Verdicts

| `verdict` | Meaning | Suggested colour |
|---|---|---|
| `VERIFIED` | Every field matches an active issuer record. | green |
| `VERIFIED_WITH_WARNINGS` | Matches, with points to review (see `signals`). | amber |
| `MATCHES_RECORD_INTEGRITY_CONCERNS` | Matches the record, but another check failed (forged QR signature, suspicious link, certificate reused in many cases). Review before accepting. | amber/red |
| `MISMATCH` | Record exists but a field differs, or the document contradicts its own signed QR / visible page. Neutral wording on purpose. | red |
| `SUSPICIOUS` | No such certificate, revoked or expired, or the QR number differs from the printed one. | red |
| `UNVERIFIABLE` | Could not decide (unknown type, issuer unreachable, OCR not installed). `reasons` says why. | grey |
| `RESCAN` | Photo or scan not good enough to read. Show `rescan_guidance`. Nothing was claimed about the document. | blue |
| `INCONCLUSIVE` | Read, but not reliably. Show `rescan_guidance`. | grey |

Treat unknown verdict values as "show the label and the reasons"; more may be added.

## Other endpoints

- `GET /api/ui-config` : app title, purposes, `max_upload_mb`, `accept` (MIME types for the file input), `verdict_labels`,
  `risk_labels`, and canned `samples` (results for demo buttons).
- `GET /api/capabilities` : `{pdf, ocr, reuse_ledger, qr_signature_keys}`; useful when photos report "not available".
- `GET /health` : `{status, records_loaded}`.

## What changed since the first version

- `/verify` now also accepts images (one endpoint, no `/scan/verify`).
- New verdicts: `VERIFIED_WITH_WARNINGS`, `MATCHES_RECORD_INTEGRITY_CONCERNS`, `RESCAN`, `INCONCLUSIVE`.
- New response fields: `risk`, `signals`, `rescan_guidance`, `fields[].confidence`, `checks.issuer_lookup`, `checks.reuse_check`;
  `input_type` can now be `scan` or `scanned_pdf`; `checks.digital_signature` can be `valid` / `invalid`.
- New request field: `fresh`.
- Existing fields keep their names and meaning.
