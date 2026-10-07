import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.formparsers import MultiPartParser

from . import config, issuer_client, security
from .issuers import mock_issuer
from .routers import auth, pages, verify
from .scan.stages import ocr
from .services import accounts, doctypes, ledger, signing

BASE_DIR = Path(__file__).resolve().parents[1]
STATIC_DIR = BASE_DIR / "static"
MAX_BODY = config.max_upload_bytes() + config.BODY_OVERHEAD  # file limit (config/ui.json) plus form overhead

# Keep uploads in memory: Starlette would otherwise spill files over 1 MB to a temp file on disk.
MultiPartParser.spool_max_size = MAX_BODY



@asynccontextmanager
async def lifespan(_: FastAPI):
    accounts.init()  # accounts are required: fail at start-up, not at the first sign-in
    ledger.init()    # create the reuse ledger now, so handling a request never creates a file
    if security.signup_mode() == "open":
        print("WARNING: sign-up is OPEN: anyone who can reach this server can create an account. "
              "Set PRAMANIK_SIGNUP_CODE or PRAMANIK_SIGNUP=closed for a real deployment.")
    yield


config.load_env()
CORS_ORIGINS = [o.strip() for o in os.environ.get("PRAMANIK_CORS_ORIGINS", "").split(",") if o.strip() and o.strip() != "*"]

app = FastAPI(title="Document Verification Platform", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)


if CORS_ORIGINS:  # only for a front end served from another address (e.g. a dev server); never "*"
    app.add_middleware(CORSMiddleware, allow_origins=CORS_ORIGINS, allow_methods=["GET", "POST"], allow_headers=["*"])


@app.middleware("http")
async def same_site_only(request: Request, call_next):
    """A browser attaches the site that made the request; refuse state-changing requests from other sites.
    (The session cookie is also SameSite=Lax. Requests without an Origin header, such as curl, pass.)"""
    if request.method in ("POST", "PUT", "PATCH", "DELETE"):
        origin = request.headers.get("origin")
        if origin and origin != "null" and origin.split("://", 1)[-1] != request.headers.get("host", "") \
                and origin not in CORS_ORIGINS:
            return JSONResponse(status_code=403, content={"detail": config.message("auth_forbidden_origin")})
    return await call_next(request)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("Permissions-Policy", "camera=(self), microphone=(), geolocation=()")
    if request.url.path.startswith("/api/") or request.url.path == "/verify":
        response.headers.setdefault("Cache-Control", "no-store")  # never cache results or account data
    if security.is_https(request):
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000")
    return response


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


app.include_router(auth.router)
app.include_router(verify.router)
app.include_router(pages.router)
app.mount("/app/js", StaticFiles(directory=pages.FRONTEND / "js"), name="app-js")
app.mount("/app/css", StaticFiles(directory=pages.FRONTEND / "css"), name="app-css")
app.mount("/app/fonts", StaticFiles(directory=pages.FRONTEND / "fonts"), name="app-fonts")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/health")
def health():
    return {"status": "ok", "records_loaded": mock_issuer.count_records()}


@app.get("/api/capabilities")
def capabilities():
    """What this server can do right now (never anything secret): useful when a scan says 'unavailable'."""
    return {"pdf": True, "ocr": ocr.available(), "reuse_ledger": ledger.enabled(),
            "qr_signature_keys": len(signing.load_keys())}


@app.get("/api/ui-config")
def ui_config():
    """Everything the pages used to hard-code: title, purposes, upload limit, verdict labels, supported documents."""
    cfg = config.public_config()
    types = doctypes.load_types()
    cfg["document_types"] = [{"id": t["id"], "title": t["title"], "issuer": issuer_client.issuer_name(t["issuer_id"])} for t in types]
    cfg["issuers"] = sorted({d["issuer"] for d in cfg["document_types"]})
    return cfg


