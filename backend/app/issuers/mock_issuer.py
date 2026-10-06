"""Adapter between the verdict rules and the issuer service.

It sends the extracted fields to the issuer service (see ../issuer_client.py) and reshapes the answer
into the dict the verdict rules read. The filename is kept so the rest of the app imports it unchanged.
"""
from .. import issuer_client
from .base import IssuerResult


def verify(document_type: str, fields: dict) -> IssuerResult:
    r = issuer_client.verify(document_type, fields)
    if r.outcome == "unconnected":
        return {"reachable": False, "found": False, "status": "", "matches": {}, "values": {},
                "error": "unconnected", "detail": r.detail}
    if r.outcome == "unavailable":
        return {"reachable": False, "found": False, "status": "", "matches": {}, "values": {},
                "error": r.error or "unreachable", "detail": r.detail}
    if r.outcome == "not_found":
        return {"reachable": True, "found": False, "status": "", "matches": {}, "values": {},
                "error": "", "detail": ""}
    return {"reachable": True, "found": True, "status": r.status, "matches": r.matches, "values": r.values,
            "error": "", "detail": ""}


def count_records() -> int:
    return issuer_client.count_records()
