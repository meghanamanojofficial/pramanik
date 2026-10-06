import hashlib
from datetime import datetime, timezone

from fastapi import APIRouter, File, Form, UploadFile
from fastapi.responses import JSONResponse

from ..issuers import mock_issuer
from ..services import compare, extract, qr_service, verdict as verdict_rules
from ..services.audit import write_audit

router = APIRouter()
MAX_BYTES = 10 * 1024 * 1024


def _error(status: int, detail: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"detail": detail})


@router.post("/verify")
async def verify(
    file: UploadFile | None = File(None),
    officer_id: str = Form(""),
    case_id: str = Form(""),
    purpose: str = Form(""),  # accepted from the form; deliberately not stored or logged
):
    if not case_id.strip():
        return _error(400, "A case or application ID is required.")

    raw = await file.read() if file is not None else b""
    if not raw or not raw.startswith(b"%PDF"):
        return _error(400, "Upload a text-based PDF.")
    if len(raw) > MAX_BYTES:
        return _error(413, "File is larger than 10 MB.")

    try:
        doc_hash = hashlib.sha256(raw).hexdigest()
        try:
            text = extract.extract_text(raw)
        except extract.UnreadablePDF:
            return _error(400, "Upload a text-based PDF.")
        doc_fields = extract.extract_fields(text)
        qr_number = qr_service.decode_qr(raw)

        decision = verdict_rules.decide(doc_fields, qr_number, mock_issuer.verify)
        rows = compare.field_rows(doc_fields, decision["issuer_result"], decision["issuer_note"])

        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        officer = officer_id.strip()[:64]
        write_audit(doc_hash, decision["verdict"], decision["route"], officer, timestamp)

        return {
            "verdict": decision["verdict"],
            "route": decision["route"],
            "input_type": "pdf",
            "coverage": compare.coverage(rows),
            "reasons": decision["reasons"],
            "fields": rows,
            "checks": {
                "qr_consistency": verdict_rules.qr_consistency(doc_fields.get("certificate_number"), qr_number),
                "pdf_metadata": "not_applicable",
                "digital_signature": "not_applicable",
            },
            "audit": {"doc_hash": doc_hash, "officer_id": officer, "timestamp": timestamp},
        }
    except Exception:
        # Generic on purpose: never echo extracted text or exception details.
        return _error(500, "Verification could not be completed.")
    finally:
        raw = None
