"""Read a photo or scan: quality gate -> page rectification -> QR -> OCR -> schema fields.

This stage never decides whether a document is genuine. It produces the same things the PDF path
produces (document type, fields, QR text) so the one set of verdict rules in services/verdict.py
applies to both. It stops early, before the issuer is asked, only when the image cannot be judged:

    RESCAN         the picture is not good enough to read (blurry, dark, washed out, too small)
    INCONCLUSIVE   it was read, but not reliably enough to compare (unreadable, low confidence,
                   two passes disagree). A shaky reading must never produce an accusation.
    UNVERIFIABLE   this server has no OCR engine installed.
"""
import threading
from typing import Optional

import numpy as np

from .. import config
from ..services import doctypes, qr_payload, verdict as verdict_rules
from ..services.reading import Reading
from ..services.signals import Severity, Signal
from .stages import codes, ocr, parse, quality, rectify

_slots: Optional[threading.BoundedSemaphore] = None
_slots_lock = threading.Lock()


def _gate() -> threading.BoundedSemaphore:
    """OCR is CPU heavy; cap how many run at once so a burst of uploads cannot starve the server."""
    global _slots
    with _slots_lock:
        if _slots is None:
            _slots = threading.BoundedSemaphore(max(1, int(config.scan()["max_concurrent_scans"])))
        return _slots


def slot():
    """Context manager: hold one of the limited OCR slots."""
    return _gate()


def read_image(raw: Optional[bytes] = None, img: Optional[np.ndarray] = None) -> Reading:
    """Give either the uploaded bytes or an already-decoded RGB array (a rendered scanned-PDF page)."""
    with _gate():
        return _read(raw, img)


def _read(raw: Optional[bytes], img: Optional[np.ndarray]) -> Reading:
    out = Reading()
    cfg = config.scan()["ocr"]

    # 1. quality gate
    if img is None:
        q_signals, img = quality.check_quality(raw)
    else:
        q_signals = quality.assess(img)
    out.signals += q_signals
    failed = [s for s in q_signals if s.severity == Severity.FAIL]
    if failed:
        out.checks["quality_gate"] = "fail"
        out.rescan_guidance = failed[0].detail
        out.early = verdict_rules.early(verdict_rules.RESCAN, [s.detail for s in failed])
        return out
    out.checks["quality_gate"] = "pass"

    # 2-3. page and QR
    page, r_signals = rectify.rectify_page(img)
    out.signals += r_signals
    out.page = page
    out.qr_raw, qr_box = codes.find_qr(page, img)

    # 4. OCR (needs Tesseract)
    if not ocr.available():
        out.checks["ocr"] = "unavailable"
        out.early = verdict_rules.early(verdict_rules.UNVERIFIABLE, [config.message("scan_ocr_unavailable")])
        return out
    gray, binary = ocr.prepare(page, qr_box)
    first = ocr.run(gray, 6, "grey_psm6")

    # 5. schema: which document is this, and what do its fields say?
    qr = qr_payload.interpret(out.qr_raw)
    doc_type = parse.detect_doc_type(first.text, qr.number)
    if doc_type is None and qr.doc_type_id:  # a valid signed token names its own document type
        doc_type = doctypes.by_id(qr.doc_type_id)
    out.text, out.doc_type = first.text, doc_type
    if doc_type is None:
        low = first.mean_conf < cfg["overall_confidence_min"]
        out.checks["ocr_confidence"] = "low" if low else "pass"
        if low:  # garbage in, not "unknown document type"
            out.rescan_guidance = config.message("scan_rescan_hint")
            out.early = verdict_rules.early(verdict_rules.INCONCLUSIVE, [config.message("scan_unreadable")])
        return out  # otherwise the shared rules report "Document type not recognised"

    reads = [parse.read_fields(doc_type, first)]
    # 6. a second look only when the first was not clearly good: different preprocessing, then cross-check
    first_values, first_conf, first_problems = parse.reconcile(doc_type, reads)
    if first_problems or any(c < cfg["second_pass_below"] for c in first_conf.values()):
        second = ocr.run(binary, 4, "binary_psm4")
        reads.append(parse.read_fields(doc_type, second))
        out.text = out.text or second.text
    values, confs, problems = parse.reconcile(doc_type, reads)
    out.fields, out.confidences = values, confs

    if problems:
        out.checks["ocr_confidence"] = "low"
        out.rescan_guidance = config.message("scan_rescan_hint")
        reasons = []
        for name, kind in problems.items():
            key = {"missing": "field_unreadable", "low": "scan_low_confidence", "inconsistent": "scan_inconsistent"}[kind]
            reasons.append(config.message(key, field=name, conf=confs.get(name, 0)))
        sev = Severity.FAIL
        out.signals += [Signal(f"ocr_{kind}", sev, config.message("scan_field_" + kind, field=name))
                        for name, kind in problems.items()]
        out.early = verdict_rules.early(verdict_rules.INCONCLUSIVE, reasons)
        return out

    out.checks["ocr_confidence"] = "pass"
    out.signals.append(Signal("ocr_completed", Severity.OK, config.message("scan_ocr_ok", conf=min(confs.values()))))
    return out

