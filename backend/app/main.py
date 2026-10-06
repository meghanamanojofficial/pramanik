from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.formparsers import MultiPartParser

from . import config
from .issuers import mock_issuer
from .routers import verify

BASE_DIR = Path(__file__).resolve().parents[1]
STATIC_DIR = BASE_DIR / "static"
MAX_BODY = config.max_upload_bytes() + config.BODY_OVERHEAD  # file limit (config/ui.json) plus form overhead

# Keep uploads in memory: Starlette would otherwise spill files over 1 MB to a temp file on disk.
MultiPartParser.spool_max_size = MAX_BODY

app = FastAPI(title="Document Verification Platform", docs_url=None, redoc_url=None)


@app.middleware("http")
async def reject_oversize(request: Request, call_next):
    # Refuse huge uploads before the body is parsed (and could be spooled to disk).
    if request.url.path == "/verify":
        length = request.headers.get("content-length")
        if length and length.isdigit() and int(length) > MAX_BODY:
            return JSONResponse(status_code=413, content={"detail": config.message("file_too_large")})
    return await call_next(request)


@app.exception_handler(RequestValidationError)
async def generic_validation_error(request: Request, exc: RequestValidationError):
    # The default handler echoes submitted values; keep it generic.
    return JSONResponse(status_code=400, content={"detail": config.message("request_unreadable")})


app.include_router(verify.router)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/health")
def health():
    return {"status": "ok", "records_loaded": mock_issuer.count_records()}


@app.get("/api/ui-config")
def ui_config():
    """Everything the page used to hard-code: title, purposes, upload limit, verdict labels, samples."""
    return config.public_config()


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")
