from fastapi import APIRouter, File, Form, UploadFile
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from .. import config
from ..services import extract, flow

router = APIRouter()


def _error(status: int, detail: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"detail": detail})


@router.post("/verify")
async def verify(
    file: UploadFile | None = File(None),
    officer_id: str = Form(""),
    case_id: str = Form(""),
    purpose: str = Form(""),  # accepted from the form; deliberately not stored or logged
    fresh: str = Form(""),    # "1": ask the issuer again instead of reusing its recent answer
):
    if not case_id.strip():
        return _error(400, config.message("case_id_required"))

    raw = await file.read() if file is not None else b""
    kind = flow.sniff(raw) if raw else None  # by content, not by filename or the browser's claim
    if kind is None:
        return _error(400, config.message("unsupported_file"))
    if len(raw) > config.max_upload_bytes():
        return _error(413, config.message("file_too_large"))

    try:
        return await run_in_threadpool(flow.run, raw, kind, officer_id.strip()[:64], case_id,
                                     fresh.strip().lower() in ("1", "true", "on", "yes"))
    except extract.UnreadablePDF:
        return _error(400, config.message("pdf_unreadable"))
    except Exception:
        # Generic on purpose: never echo extracted text or exception details.
        return _error(500, config.message("verification_failed"))
    finally:
        raw = None
