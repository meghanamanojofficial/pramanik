"""Talks to issuer services over HTTP. Everything about *who* to call lives in
config/issuers.json; secrets live in environment variables (backend/.env).

lookup() never raises. It returns an IssuerResult whose outcome is one of:
  found        -> issuer has the record (result.record)
  not_found    -> issuer is connected but has no such certificate
  unconnected  -> no issuer configured for this certificate prefix
  unavailable  -> issuer unreachable / rejected our key / bad response
Callers should map "unconnected" to UNVERIFIABLE and "unavailable" to
NEEDS REVIEW, never to TAMPERED or SUSPICIOUS.
"""
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

BACKEND_DIR = Path(__file__).resolve().parent.parent
_env_loaded = False


@dataclass
class IssuerResult:
    outcome: str
    record: Optional[dict] = None
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


def _route(cert_number: str, issuers: list) -> Optional[dict]:
    best, best_len = None, -1
    for issuer in issuers:
        for prefix in issuer["prefixes"]:
            if cert_number.upper().startswith(prefix.upper()) and len(prefix) > best_len:
                best, best_len = issuer, len(prefix)
    return best


def lookup(cert_number: str) -> IssuerResult:
    _load_dotenv()
    issuer = _route(cert_number, load_config())
    if issuer is None:
        return IssuerResult("unconnected", detail="no issuer configured for this certificate series")

    iid = issuer["issuer_id"]
    api_key = os.environ.get(issuer["api_key_env"])
    if not api_key:
        return IssuerResult("unavailable", issuer_id=iid,
                            detail=f"{issuer['api_key_env']} is not set (run setup_keys.py)")

    url = f"{issuer['base_url'].rstrip('/')}/v1/records/{quote(cert_number, safe='')}"
    req = Request(url, headers={"X-API-Key": api_key, "Accept": "application/json"})
    try:
        with urlopen(req, timeout=issuer.get("timeout_seconds", 5)) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        return IssuerResult("found", record=body["record"], issuer_id=iid)
    except HTTPError as e:
        if e.code == 404:
            return IssuerResult("not_found", issuer_id=iid)
        return IssuerResult("unavailable", issuer_id=iid, detail=f"issuer returned HTTP {e.code}")
    except (URLError, TimeoutError, OSError):
        return IssuerResult("unavailable", issuer_id=iid, detail="issuer unreachable")
    except (ValueError, KeyError):
        return IssuerResult("unavailable", issuer_id=iid, detail="malformed issuer response")
