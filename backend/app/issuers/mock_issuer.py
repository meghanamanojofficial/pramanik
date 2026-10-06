"""Simulated issuer. Reads data/mock_records.json on every call, so edits apply without a restart.

Issuer values come only from that file, never from the uploaded document.
"""
import json
import re
from pathlib import Path

from rapidfuzz import fuzz

from .base import IssuerResult
from ..issuer_client import lookup

RECORDS_FILE = Path(__file__).resolve().parents[2] / "data" / "mock_records.json"

_NUMBER_RE = re.compile(r"^INC-\d{4}-\d{4}$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_STATUSES = {"active", "revoked", "expired"}
_FIELDS = ("certificate_number", "holder_name", "issue_date", "income_amount")
NAME_THRESHOLD = 90


def _valid(record) -> bool:
    return (
        isinstance(record, dict)
        and all(isinstance(record.get(k), str) for k in (*_FIELDS, "status"))
        and bool(_NUMBER_RE.match(record["certificate_number"]))
        and bool(record["holder_name"].strip())
        and bool(_DATE_RE.match(record["issue_date"]))
        and record["income_amount"].isdigit()
        and record["status"] in _STATUSES
    )


def load_records() -> list[dict] | None:
    """Return the records, or None if the file is missing or invalid."""
    try:
        data = json.loads(RECORDS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, list) or not all(_valid(r) for r in data):
        return None
    return data


def count_records() -> int:
    records = load_records()
    return len(records) if records is not None else 0


def _norm(field: str, value: str) -> str:
    value = re.sub(r"\s+", " ", (value or "").strip())
    if field == "income_amount":
        return re.sub(r"\D", "", value)
    if field == "holder_name":
        return value.lower()
    return value


def _field_matches(field: str, document_value: str, issuer_value: str) -> bool:
    a, b = _norm(field, document_value), _norm(field, issuer_value)
    if field == "holder_name":
        return fuzz.token_sort_ratio(a, b) >= NAME_THRESHOLD
    return a == b

def verify(certificate_number: str, fields: dict[str, str]) -> IssuerResult:
    wanted = _norm("certificate_number", certificate_number)
    result = lookup(wanted)  # HTTP call to the issuer service, with the API key

    if result.outcome in ("unavailable", "unconnected"):
        return {"reachable": False, "found": False, "status": "", "matches": {}, "values": {}}
    if result.outcome == "not_found":
        return {"reachable": True, "found": False, "status": "", "matches": {}, "values": {}}
    record = result.record

    matches = {f: _field_matches(f, fields.get(f, ""), record[f]) for f in _FIELDS}
    values = {f: record[f] for f in _FIELDS}
    return {"reachable": True, "found": True, "status": record["status"], "matches": matches, "values": values}
