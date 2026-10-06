"""Sends the fields extracted from a document to the issuing authority over HTTP.

Which authority handles which document type is in config/issuers.json; the key is read
from the environment variable named there (backend/.env).

verify() never raises. It returns an IssuerResult whose outcome is one of:
  found        -> issuer has a record; .status and .matches (per field) are filled in
  not_found    -> issuer is connected but has no such certificate
  unconnected  -> no issuer configured for this document type
  unavailable  -> issuer unreachable / rejected our key / bad response
"""
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

BACKEND_DIR = Path(__file__).resolve().parent.parent
_env_loaded = False


@dataclass
class IssuerResult:
    outcome: str
    status: str = ""
    matches: dict = field(default_factory=dict)
    values: dict = field(default_factory=dict)
    issuer_id: Optional[str] = None
    detail: str = ""


def _load_dotenv() -> None:
    """Minimal .env reader; real environment variables always win."""
    global _env_loaded
    if _env_loaded:
        return
    _env_loaded = True
    path = BACKEND_DIR / ".env"
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


def load_config() -> list:
    path = Path(os.environ.get("ISSUERS_CONFIG", BACKEND_DIR / "config" / "issuers.json"))
    return json.loads(path.read_text(encoding="utf-8"))["issuers"]


def _route(document_type: str, issuers: list) -> Optional[dict]:
    return next((i for i in issuers if document_type in i["document_types"]), None)


def _call(issuer: dict, method: str, path: str, payload: Optional[dict] = None):
    """Returns (http_status, body_dict). Raises URLError/OSError on network failure."""
    api_key = os.environ.get(issuer["api_key_env"])
    if not api_key:
        raise KeyError(f"{issuer['api_key_env']} is not set (run setup_keys.py)")
    headers = {"X-API-Key": api_key, "Accept": "application/json"}
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = Request(issuer["base_url"].rstrip("/") + path, data=data, headers=headers, method=method)
    try:
        with urlopen(req, timeout=issuer.get("timeout_seconds", 5)) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except HTTPError as e:
        return e.code, {}


def verify(document_type: str, fields: dict) -> IssuerResult:
    _load_dotenv()
    issuer = _route(document_type, load_config())
    if issuer is None:
        return IssuerResult("unconnected", detail="no issuer configured for this document type")
    iid = issuer["issuer_id"]
    try:
        code, body = _call(issuer, "POST", "/v1/verify", {"document_type": document_type, "fields": fields})
    except KeyError as e:
        return IssuerResult("unavailable", issuer_id=iid, detail=str(e).strip("'\""))
    except (URLError, TimeoutError, OSError):
        return IssuerResult("unavailable", issuer_id=iid, detail="issuer unreachable")
    except ValueError:
        return IssuerResult("unavailable", issuer_id=iid, detail="malformed issuer response")
    if code != 200:
        return IssuerResult("unavailable", issuer_id=iid, detail=f"issuer returned HTTP {code}")
    if not body.get("found"):
        return IssuerResult("not_found", issuer_id=iid)
    return IssuerResult("found", status=body.get("status", ""), matches=body.get("matches", {}),
                        values=body.get("values") or {}, issuer_id=iid)


def count_records() -> int:
    """Total records the connected issuers report (used by /health). 0 if none can be reached."""
    _load_dotenv()
    total = 0
    for issuer in load_config():
        try:
            code, body = _call(issuer, "GET", "/v1/stats")
        except (KeyError, URLError, TimeoutError, OSError, ValueError):
            continue
        if code == 200:
            total += int(body.get("records_loaded", 0))
    return total
