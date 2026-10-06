"""Verdict rules, evaluated top to bottom; the first match wins."""
from typing import Callable

from ..issuers.base import IssuerResult
from .compare import NOT_FOUND, NOT_QUERIED, UNREACHABLE
from .extract import FIELD_ORDER

VERIFIED, SUSPICIOUS, TAMPERED, UNVERIFIABLE = "VERIFIED", "SUSPICIOUS", "TAMPERED", "UNVERIFIABLE"


def qr_consistency(printed_number: str | None, qr_number: str | None) -> str:
    if not qr_number or not printed_number:
        return "not_applicable"
    return "pass" if qr_number == printed_number else "fail"


def decide(doc_fields: dict, qr_number: str | None,
           query_issuer: Callable[[str, dict], IssuerResult]) -> dict:
    """Returns verdict, route, reasons, issuer_result and issuer_note (what to show as the issuer value)."""
    printed = doc_fields.get("certificate_number")

    def out(verdict, reasons, route="none", issuer_result=None, note=NOT_QUERIED):
        return {"verdict": verdict, "reasons": reasons, "route": route,
                "issuer_result": issuer_result, "issuer_note": note}

    # 1. Anything unreadable
    missing = [f for f in FIELD_ORDER if not doc_fields.get(f)]
    if missing:
        return out(UNVERIFIABLE, [f"Could not read {f} from the document." for f in missing])

    # 2. QR disagrees with the printed number; the issuer is not asked
    if qr_number and qr_number != printed:
        return out(SUSPICIOUS, ["QR code number differs from the printed certificate number."])

    # 3-7. Ask the issuer
    lookup_number = qr_number or printed
    result = query_issuer(lookup_number, {f: doc_fields[f] for f in FIELD_ORDER})

    if not result["reachable"]:
        return out(UNVERIFIABLE, ["Issuer could not be reached."], "direct_issuer", result, UNREACHABLE)
    if not result["found"]:
        return out(SUSPICIOUS, ["Issuer has no record of this certificate number."], "direct_issuer", result, NOT_FOUND)

    mismatched = [f for f in FIELD_ORDER if not result["matches"].get(f, False)]
    if mismatched:
        return out(TAMPERED, [f"{f} on the document does not match the issuer record." for f in mismatched],
                   "direct_issuer", result)
    if result["status"] != "active":
        return out(SUSPICIOUS, [f"Issuer lists this certificate as {result['status']}."], "direct_issuer", result)
    return out(VERIFIED, ["All printed fields match the issuer record."], "direct_issuer", result)
