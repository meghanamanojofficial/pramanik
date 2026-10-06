"""Verdict rules, evaluated top to bottom; the first match wins."""
from typing import Callable, Optional

from .. import config
from ..issuers.base import IssuerResult
from .compare import NOT_FOUND, NOT_QUERIED, UNAVAILABLE, UNREACHABLE
from .doctypes import field_names, key_field
from .signals import Severity, Signal

# MISMATCH means "the printed fields do not match the issuer record". It does not say why:
# a clerical error or registry lag looks the same as an edit, so the wording stays neutral.
VERIFIED, SUSPICIOUS, MISMATCH, UNVERIFIABLE = "VERIFIED", "SUSPICIOUS", "MISMATCH", "UNVERIFIABLE"
# Refinements of VERIFIED, from the extra checks in app/checks (the issuer still said "matches"):
VERIFIED_WITH_WARNINGS = "VERIFIED_WITH_WARNINGS"
INTEGRITY_CONCERNS = "MATCHES_RECORD_INTEGRITY_CONCERNS"
# Photos and scans only: the check could not be made, so nothing is claimed about the document itself.
RESCAN = "RESCAN"              # the image is not good enough to read
INCONCLUSIVE = "INCONCLUSIVE"  # it was read, but not reliably enough to compare


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
        return out(UNVERIFIABLE, [config.message("doc_type_unrecognised")])

    names = field_names(doc_type)
    printed = doc_fields.get(key_field(doc_type))

    # 1. Anything unreadable
    missing = [f for f in names if not doc_fields.get(f)]
    if missing:
        return out(UNVERIFIABLE, [config.message("field_unreadable", field=f) for f in missing])

    # 2. QR disagrees with the printed number; the issuer is not asked
    if qr_number and qr_number != printed:
        return out(SUSPICIOUS, [config.message("qr_mismatch")])

    # 3-7. Send the extracted fields to the issuing authority
    result = query_issuer(doc_type["id"], {f: doc_fields[f] for f in names})

    if not result["reachable"]:
        code = result.get("error") or "unreachable"
        note = UNREACHABLE if code == "unreachable" else UNAVAILABLE
        return out(UNVERIFIABLE, [config.issuer_error_message(code, result.get("detail", ""))],
                   "direct_issuer", result, note)
    if not result["found"]:
        return out(SUSPICIOUS, [config.message("not_found")], "direct_issuer", result, NOT_FOUND)

    mismatched = [f for f in names if not result["matches"].get(f, False)]
    if mismatched:
        return out(MISMATCH, [config.message("field_mismatch", field=f) for f in mismatched],
                   "direct_issuer", result)
    if result["status"] != doc_type.get("valid_status", "active"):
        return out(SUSPICIOUS, [config.message("status_not_valid", status=result["status"])],
                   "direct_issuer", result)
    return out(VERIFIED, [config.message("all_match")], "direct_issuer", result)


def early(verdict: str, reasons: list, route: str = "none") -> dict:
    """A result reached before the issuer is asked (bad image, unreliable reading)."""
    return {"verdict": verdict, "reasons": reasons, "route": route, "issuer_result": None, "issuer_note": NOT_QUERIED}


def finalize(decision: dict, signals: list[Signal], scanned: bool = False) -> dict:
    """Refine a decision with the extra signals. Only VERIFIED can change, and only for the worse or
    with a caveat: a clean extra check never turns a mismatch, a missing record or a revoked certificate
    into anything better.

      a field differs from the issuer-signed QR     -> MISMATCH
      a STRONG signal (forged signature, link ...)  -> MATCHES_RECORD_INTEGRITY_CONCERNS
      a WEAK signal                                 -> VERIFIED_WITH_WARNINGS

    For photos and scans, a negative verdict also carries a reminder that the values were read by OCR.
    """
    out = dict(decision)
    verdict = decision["verdict"]

    if verdict == VERIFIED:
        failed = [x for x in signals if x.severity == Severity.FAIL]
        strong = [x for x in signals if x.severity == Severity.STRONG]
        weak = [x for x in signals if x.severity == Severity.WEAK]
        if failed:
            out.update(verdict=MISMATCH, reasons=[x.detail for x in failed])
        elif strong:
            out.update(verdict=INTEGRITY_CONCERNS,
                       reasons=[config.message("integrity_concerns")] + [x.detail for x in strong + weak])
        elif weak:
            out.update(verdict=VERIFIED_WITH_WARNINGS,
                       reasons=[config.message("all_match_with_warnings")] + [x.detail for x in weak])
    elif scanned and verdict in (MISMATCH, SUSPICIOUS):
        out["reasons"] = list(decision["reasons"]) + [config.message("scan_read_caveat")]
    return out
