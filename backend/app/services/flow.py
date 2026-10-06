"""One verification for every kind of input.

A front-end turns the upload into a Reading (document type, fields, QR text): the PDF text layer for
digital PDFs, OCR for photos, scans and image-only PDFs. From there everything is shared:

    QR meaning -> issuer lookup + verdict rules -> field rows -> extra checks -> finalize -> ledger -> audit

so a photo and a PDF of the same certificate are judged by exactly the same rules.
"""
import hashlib
from datetime import datetime, timezone
from typing import Optional

from .. import config
from ..checks import consistency, links, reuse, signed_qr, visual
from .. import issuer_client
from ..issuers import mock_issuer
from ..scan import pipeline as scan_pipeline
from . import compare, doctypes, extract, issuer_cache, ledger, qr_payload, qr_service, risk, verdict as verdict_rules
from .audit import OFFICER_ID_SOURCE, write_audit
from .reading import Reading
from .signals import Severity, Signal

PDF, IMAGE = "pdf", "image"


def sniff(raw: bytes) -> Optional[str]:
    """What the bytes are, whatever the filename or the browser's content type claims."""
    if raw.startswith(b"%PDF"):
        return PDF
    if raw[:3] == b"\xff\xd8\xff" or raw[:8] == b"\x89PNG\r\n\x1a\n" or (raw[:4] == b"RIFF" and raw[8:12] == b"WEBP"):
        return IMAGE
    return None


def _read_pdf(raw: bytes) -> tuple[Reading, str]:
    """Text layer if there is one; otherwise the page is an image and goes through OCR like a photo."""
    text = extract.extract_text(raw)
    cfg = config.scan()["scanned_pdf"]
    page = qr_service.render_page_one(raw, cfg["dpi"])
    if len(text.strip()) < cfg["min_text_chars"]:
        if page is None:
            raise extract.UnreadablePDF
        return scan_pipeline.read_image(img=page), "scanned_pdf"
    doc_type = doctypes.detect(text)
    fields = extract.extract_fields(text, doc_type) if doc_type else {}
    hits = qr_service.decode_array(page) if page is not None else []
    signals = [Signal("pdf_conflicting_text", Severity.STRONG, config.message("pdf_conflicting_text", field=name), region=name)
               for name in (extract.conflicts(text, doc_type) if doc_type else [])]
    signals += visual.check(doc_type, fields, page)
    return Reading(doc_type=doc_type, fields=fields, qr_raw=hits[0].data if hits else None, text=text,
                   signals=signals, page=page), "pdf"


def run(raw: bytes, kind: str, officer: str, case_id: str, fresh: bool = False,
        officer_source: str = OFFICER_ID_SOURCE) -> dict:
    """The whole blocking pipeline; the route runs it in a worker thread.
    `fresh` skips the issuer-answer cache for this check. Raises extract.UnreadablePDF for unopenable PDFs."""
    doc_hash = hashlib.sha256(raw).hexdigest()
    if kind == PDF:
        reading, input_type = _read_pdf(raw)
    else:
        reading, input_type = scan_pipeline.read_image(raw=raw), "scan"
    return _conclude(reading, input_type, doc_hash, officer, case_id, fresh, officer_source)


def _conclude(rd: Reading, input_type: str, doc_hash: str, officer: str, case_id: str, fresh: bool = False,
              officer_source: str = OFFICER_ID_SOURCE) -> dict:
    scanned = input_type != "pdf"
    qr = qr_payload.interpret(rd.qr_raw)
    signals = list(rd.signals)
    rows: list = []
    stamp = None
    complete = False

    if rd.early:
        decision = rd.early
    else:
        signals += signed_qr.check(qr, expect_qr=scanned)
        decision = verdict_rules.decide(rd.doc_type, rd.fields, qr.number,
                                        lambda t, f: issuer_cache.verify(mock_issuer.verify, t, f, fresh))
        answer = decision["issuer_result"] or {}
        if answer.get("source") == "cache":
            signals.append(Signal("issuer_answer_cached", Severity.OK,
                                  config.message("issuer_cached", minutes=max(1, round(answer["age_seconds"] / 60)))))
        rows = compare.field_rows(rd.doc_type, rd.fields, decision["issuer_result"], decision["issuer_note"])
        for row in rows:
            if row["field"] in rd.confidences:
                row["confidence"] = rd.confidences[row["field"]]
        signals += consistency.check(rd.doc_type, rd.fields, qr)
        signals += links.check(rd.text)
        complete = rd.doc_type is not None and all(rd.fields.get(n) for n in doctypes.field_names(rd.doc_type))
        if complete:
            stamp = reuse.stamp_hash(rd.page, rd.doc_type) if scanned else None
            signals += reuse.check(rd.doc_type, rd.fields, case_id, input_type, stamp)
        decision = verdict_rules.finalize(decision, signals, scanned)

    verdict = decision["verdict"]
    if complete:  # remember it so a later check in another case can spot reuse; failure is silent
        ledger.record(rd.doc_type, rd.fields, case_id, input_type, verdict, stamp)

    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    issuer_source = (decision.get("issuer_result") or {}).get("source")
    if issuer_source is None and decision.get("issuer_result"):
        issuer_source = "live"
    write_audit(doc_hash, verdict, decision["route"], officer, timestamp, input_type, issuer_source or "none", officer_source)

    printed_key = rd.fields.get(doctypes.key_field(rd.doc_type)) if rd.doc_type else None
    checks = {"qr_consistency": verdict_rules.qr_consistency(printed_key, qr.number)}
    if not scanned:
        checks["pdf_metadata"] = "not_applicable"
    checks["digital_signature"] = qr.digital_signature
    checks.update(rd.checks)
    if issuer_source and (decision["issuer_result"] or {}).get("reachable"):
        checks["issuer_lookup"] = issuer_source
    if complete and ledger.enabled():
        checks["reuse_check"] = "flagged" if any(s.name.startswith(("duplicate_", "stamp_")) for s in signals) else "pass"

    return {
        "verdict": verdict,
        "route": decision["route"],
        "input_type": input_type,
        "document_type": rd.doc_type["id"] if rd.doc_type else None,
        "document_title": rd.doc_type["title"] if rd.doc_type else None,
        "issuer": ({"id": rd.doc_type["issuer_id"], "name": issuer_client.issuer_name(rd.doc_type["issuer_id"])}
                   if rd.doc_type else None),
        "coverage": compare.coverage(rows),
        "reasons": decision["reasons"],
        "fields": rows,
        "checks": checks,
        "risk": risk.assess(verdict, signals, input_type, rd.confidences, qr.digital_signature),
        "signals": [s.to_dict() for s in signals],
        "rescan_guidance": rd.rescan_guidance,
        "audit": {"doc_hash": doc_hash, "officer_id": officer, "officer_id_source": officer_source,
                  "timestamp": timestamp},
    }
