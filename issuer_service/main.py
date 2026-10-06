"""Mock government-department issuer service (separate process, port 8002).

Run from the issuer_service/ folder:
    uvicorn main:app --reload --port 8002
"""
import os
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Header
from fastapi.responses import JSONResponse

from core import IssuerCore

BASE = Path(__file__).parent
core = IssuerCore(
    registries_path=os.environ.get("ISSUER_REGISTRIES", BASE / "registries.json"),
    keys_path=os.environ.get("ISSUER_KEYS_FILE", BASE / "keys.json"),
    audit_path=os.environ.get("ISSUER_AUDIT_LOG", BASE / "audit.jsonl"),
    rate_limit_per_minute=int(os.environ.get("ISSUER_RATE_LIMIT", "60")),
)

app = FastAPI(title="Pramanik mock issuer service")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/v1/records/{certificate_number}")
def get_record(certificate_number: str, x_api_key: Optional[str] = Header(default=None)):
    status, body = core.lookup(x_api_key, certificate_number)
    return JSONResponse(status_code=status, content=body)
