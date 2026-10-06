from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from .. import config, security
from ..services import audit, extract, flow

router = APIRouter()


def _error(status: int, detail: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"detail": detail})


@router.post("/verify")
async def verify(
    request: Request,
    file: UploadFile | None = File(None),
    officer_id: str = Form(""),  # ignored: the officer is the signed-in account (kept so older clients still post)
    case_id: str = Form(""),
    purpose: str = Form(""),  # accepted from the form; deliberately not stored or logged
    fresh: str = Form(""),    # "1": ask the issuer again instead of reusing its recent answer
):
    user = security.require_profile(request)
    if not case_id.strip():
        return _error(400, config.message("case_id_required"))

    raw = await file.read() if file is not None else b""
    kind = flow.sniff(raw) if raw else None  # by content, not by filename or the browser's claim
    if kind is None:
        return _error(400, config.message("unsupported_file"))
    if len(raw) > config.max_upload_bytes():
        return _error(413, config.message("file_too_large"))

    try:
        return await run_in_threadpool(flow.run, raw, kind, user.officer_id, case_id.strip()[:64],
                                     fresh.strip().lower() in ("1", "true", "on", "yes"))
    except extract.UnreadablePDF:
        return _error(400, config.message("pdf_unreadable"))
    except Exception:
        # Generic on purpose: never echo extracted text or exception details.
        return _error(500, config.message("verification_failed"))
    finally:
        raw = None


@router.get("/api/history")
def history(request: Request, limit: int = 20):
    """This officer's recent checks (from the audit log: verdict, time, document hash; never names or content)."""
    user = security.require_profile(request)
    return audit.recent(user.officer_id, max(1, min(limit, 100)))
