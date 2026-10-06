"""Mock government-department issuer service (separate process, port 8002).

Run from the issuer_service/ folder:
    uvicorn main:app --reload --port 8002
"""
import os
from pathlib import Path
from typing import Dict, Optional

from fastapi import FastAPI, Header
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from core import IssuerCore

BASE = Path(__file__).parent
core = IssuerCore(
    registries_path=os.environ.get("ISSUER_REGISTRIES", BASE / "registries.json"),
    keys_path=os.environ.get("ISSUER_KEYS_FILE", BASE / "keys.json"),
    audit_path=os.environ.get("ISSUER_AUDIT_LOG", BASE / "audit.jsonl"),
    rate_limit_per_minute=int(os.environ.get("ISSUER_RATE_LIMIT", "60")),
)

app = FastAPI(title="Pramanik mock issuer service")


class VerifyRequest(BaseModel):
    document_type: str
    fields: Dict[str, Optional[str]]


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/v1/verify")
def verify(req: VerifyRequest, x_api_key: Optional[str] = Header(default=None)):
    status, body = core.verify(x_api_key, req.document_type, req.fields)
    return JSONResponse(status_code=status, content=body)


@app.get("/v1/stats")
def stats(x_api_key: Optional[str] = Header(default=None)):
    status, body = core.stats(x_api_key)
    return JSONResponse(status_code=status, content=body)
