import hashlib
from datetime import datetime, timezone

from fastapi import APIRouter, File, Form, UploadFile
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from .. import config
from ..issuers import mock_issuer
from ..services import compare, doctypes, extract, qr_service, verdict as verdict_rules
from ..services.audit import OFFICER_ID_SOURCE, write_audit

router = APIRouter()


def _error(status: int, detail: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"detail": detail})


def _process(raw: bytes, officer: str) -> dict:
    """The whole blocking pipeline: PDF parsing, QR decoding, the HTTP call to the issuer, the audit write.

    It runs in a worker thread (see verify() below) so a slow issuer or a heavy PDF cannot stall the
    event loop and freeze every other officer's request. Raises extract.UnreadablePDF for bad PDFs.
    """
    doc_hash = hashlib.sha256(raw).hexdigest()
    text = extract.extract_text(raw)

    # 1. work out what kind of document this is, and read its fields (all from the schema)
    doc_type = doctypes.detect(text)
    doc_fields = extract.extract_fields(text, doc_type) if doc_type else {}
    qr_number = qr_service.decode_qr(raw)

    # 2. send the extracted fields to the issuing authority and apply the verdict rules
    decision = verdict_rules.decide(doc_type, doc_fields, qr_number, mock_issuer.verify)
    rows = compare.field_rows(doc_type, doc_fields, decision["issuer_result"], decision["issuer_note"])

    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    write_audit(doc_hash, decision["verdict"], decision["route"], officer, timestamp)

    printed_key = doc_fields.get(doctypes.key_field(doc_type)) if doc_type else None
    return {
        "verdict": decision["verdict"],
        "route": decision["route"],
        "input_type": "pdf",
        "document_type": doc_type["id"] if doc_type else None,
        "coverage": compare.coverage(rows),
        "reasons": decision["reasons"],
        "fields": rows,
        "checks": {
            "qr_consistency": verdict_rules.qr_consistency(printed_key, qr_number),
            "pdf_metadata": "not_applicable",
            "digital_signature": "not_applicable",
        },
        "audit": {"doc_hash": doc_hash, "officer_id": officer, "officer_id_source": OFFICER_ID_SOURCE,
                  "timestamp": timestamp},
    }


@router.post("/verify")
async def verify(
    file: UploadFile | None = File(None),
    officer_id: str = Form(""),
    case_id: str = Form(""),
    purpose: str = Form(""),  # accepted from the form; deliberately not stored or logged
):
    if not case_id.strip():
        return _error(400, config.message("case_id_required"))

    raw = await file.read() if file is not None else b""
    if not raw or not raw.startswith(b"%PDF"):
        return _error(400, config.message("not_pdf"))
    if len(raw) > config.max_upload_bytes():
        return _error(413, config.message("file_too_large"))

    try:
        return await run_in_threadpool(_process, raw, officer_id.strip()[:64])
    except extract.UnreadablePDF:
        return _error(400, config.message("not_pdf"))
    except Exception:
        # Generic on purpose: never echo extracted text or exception details.
        return _error(500, config.message("verification_failed"))
    finally:
        raw = None
