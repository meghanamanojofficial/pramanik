"""Adapter between the verdict rules and the issuer service.

The old in-process mock lived here and read mock_records.json directly. It now just sends the
extracted fields to the issuer service (see ../issuer_client.py) and reshapes the answer.
The filename is kept so the rest of the app imports it unchanged.
"""
from .. import issuer_client
from .base import IssuerResult

_NOT_REACHED = {"reachable": False, "found": False, "status": "", "matches": {}, "values": {}}


def verify(document_type: str, fields: dict) -> IssuerResult:
    r = issuer_client.verify(document_type, fields)
    if r.outcome in ("unavailable", "unconnected"):
        return dict(_NOT_REACHED)
    if r.outcome == "not_found":
        return {"reachable": True, "found": False, "status": "", "matches": {}, "values": {}}
    return {"reachable": True, "found": True, "status": r.status, "matches": r.matches, "values": r.values}


def count_records() -> int:
    return issuer_client.count_records()
