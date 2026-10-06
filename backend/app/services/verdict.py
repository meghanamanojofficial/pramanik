"""Verdict rules, evaluated top to bottom; the first match wins."""
from typing import Callable, Optional

from ..issuers.base import IssuerResult
from .compare import NOT_FOUND, NOT_QUERIED, UNREACHABLE
from .doctypes import field_names, key_field

VERIFIED, SUSPICIOUS, TAMPERED, UNVERIFIABLE = "VERIFIED", "SUSPICIOUS", "TAMPERED", "UNVERIFIABLE"


def qr_consistency(printed_number: Optional[str], qr_number: Optional[str]) -> str:
    if not qr_number or not printed_number:
        return "not_applicable"
    return "pass" if qr_number == printed_number else "fail"


def decide(doc_type: Optional[dict], doc_fields: dict, qr_number: Optional[str],
           query_issuer: Callable[[str, dict], IssuerResult]) -> dict:
    """Returns verdict, route, reasons, issuer_result and issuer_note (what to show as the issuer value).

    query_issuer(document_type_id, fields) sends the extracted fields to the issuing authority.
    """
    def out(verdict, reasons, route="none", issuer_result=None, note=NOT_QUERIED):
        return {"verdict": verdict, "reasons": reasons, "route": route,
                "issuer_result": issuer_result, "issuer_note": note}

    # 0. We could not tell what kind of document this is
    if doc_type is None:
        return out(UNVERIFIABLE, ["Document type not recognised."])

    names = field_names(doc_type)
    printed = doc_fields.get(key_field(doc_type))

    # 1. Anything unreadable
    missing = [f for f in names if not doc_fields.get(f)]
    if missing:
        return out(UNVERIFIABLE, [f"Could not read {f} from the document." for f in missing])

    # 2. QR disagrees with the printed number; the issuer is not asked
    if qr_number and qr_number != printed:
        return out(SUSPICIOUS, ["QR code number differs from the printed certificate number."])

    # 3-7. Send the extracted fields to the issuing authority
    result = query_issuer(doc_type["id"], {f: doc_fields[f] for f in names})

    if not result["reachable"]:
        return out(UNVERIFIABLE, ["Issuer could not be reached."], "direct_issuer", result, UNREACHABLE)
    if not result["found"]:
        return out(SUSPICIOUS, ["Issuer has no record of this certificate number."], "direct_issuer", result, NOT_FOUND)

    mismatched = [f for f in names if not result["matches"].get(f, False)]
    if mismatched:
        return out(TAMPERED, [f"{f} on the document does not match the issuer record." for f in mismatched],
                   "direct_issuer", result)
    if result["status"] != doc_type.get("valid_status", "active"):
        return out(SUSPICIOUS, [f"Issuer lists this certificate as {result['status']}."], "direct_issuer", result)
    return out(VERIFIED, ["All printed fields match the issuer record."], "direct_issuer", result)
