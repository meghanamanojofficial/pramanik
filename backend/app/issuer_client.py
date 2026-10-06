"""Sends the fields extracted from a document to the issuing authority over HTTP.

Which authority handles which document type is in config/issuers.json; the key is read
from the environment variable named there (backend/.env).

verify() never raises. It returns an IssuerResult whose outcome is one of:
  found        -> issuer has a record; .status and .matches (per field) are filled in
  not_found    -> issuer is connected but has no such certificate
  unconnected  -> no issuer configured for this document type
  unavailable  -> the issuer could not answer; .error says why (see ERROR_* below)

Error codes (IssuerResult.error), each with its own officer-facing text in config/ui.json:
  unreachable          network failure or timeout
  not_configured       no API key in the environment
  key_rejected         issuer answered 401/403/404 (bad key, or key not allowed for this issuer)
  rate_limited         issuer answered 429
  registry_unavailable issuer answered 503 (its records could not be read)
  bad_response         200 but not valid JSON
  insecure_transport   issuer URL is plain HTTP and not localhost (the API key would cross the network unencrypted)
  http_error           any other HTTP status (detail holds the status)
"""
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from . import config

BACKEND_DIR = Path(__file__).resolve().parent.parent
_env_loaded = False
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}
HTTP_ERROR_CODES = {401: "key_rejected", 403: "key_rejected", 404: "key_rejected",
                    429: "rate_limited", 503: "registry_unavailable"}


class InsecureTransport(Exception):
    pass


@dataclass
class IssuerResult:
    outcome: str
    status: str = ""
    matches: dict = field(default_factory=dict)
    values: dict = field(default_factory=dict)
    issuer_id: Optional[str] = None
    detail: str = ""
    error: str = ""  # set when outcome == "unavailable" (see error codes above)


def _load_dotenv() -> None:
    """Read backend/.env (real environment variables always win). Kept as a function so tests can stub it."""
    global _env_loaded
    if _env_loaded:
        return
    _env_loaded = True
    config.load_env()


def load_config() -> list:
    path = Path(os.environ.get("ISSUERS_CONFIG", BACKEND_DIR / "config" / "issuers.json"))
    return json.loads(path.read_text(encoding="utf-8"))["issuers"]


def issuer_name(issuer_id: str) -> str:
    """Display name for an issuer id (config/issuers.json), falling back to the id."""
    return next((i.get("name", issuer_id) for i in load_config() if i["issuer_id"] == issuer_id), issuer_id)


def _route(document_type: str, issuers: list) -> Optional[dict]:
    return next((i for i in issuers if document_type in i["document_types"]), None)


def _check_transport(base_url: str) -> None:
    """Refuse to send the API key over plain HTTP to anything but this machine.
    Set PRAMANIK_ALLOW_INSECURE_HTTP=1 to override (for example inside a private test network)."""
    url = urlparse(base_url)
    if url.scheme == "https" or url.hostname in LOCAL_HOSTS:
        return
    if os.environ.get("PRAMANIK_ALLOW_INSECURE_HTTP") == "1":
        return
    raise InsecureTransport(base_url)


def _call(issuer: dict, method: str, path: str, payload: Optional[dict] = None):
    """Returns (http_status, body_dict). Raises URLError/OSError on network failure."""
    _check_transport(issuer["base_url"])
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

    def unavailable(error: str, detail: str = "") -> IssuerResult:
        return IssuerResult("unavailable", issuer_id=iid, error=error, detail=detail)

    try:
        code, body = _call(issuer, "POST", "/v1/verify", {"document_type": document_type, "fields": fields})
    except InsecureTransport:
        return unavailable("insecure_transport", "plain HTTP to a non-local issuer")
    except KeyError as e:
        return unavailable("not_configured", str(e).strip("'\""))
    except (URLError, TimeoutError, OSError):
        return unavailable("unreachable", "issuer unreachable")
    except ValueError:
        return unavailable("bad_response", "malformed issuer response")
    if code != 200:
        return unavailable(HTTP_ERROR_CODES.get(code, "http_error"), f"issuer returned HTTP {code}")
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
        except (KeyError, InsecureTransport, URLError, TimeoutError, OSError, ValueError):
            continue
        if code == 200:
            total += int(body.get("records_loaded", 0))
    return total
