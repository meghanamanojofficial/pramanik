"""Reuse the issuer's recent answer instead of asking again.

What is cached is the *issuer's answer* (found / status / per-field matches), not the final verdict:
the verdict also depends on things that must be recomputed on every check (reuse across cases, the QR
signature, image quality), so those still run every time.

Safety rules, each one a deliberate choice:
  * The key is a keyed fingerprint of EVERY extracted field. A document with any edited value has a
    different key, so it can never be answered from a genuine certificate's entry.
  * Entries expire (config/cache.json, default 10 minutes) because a certificate can be revoked.
  * Only a clear "record found" answer is stored. "Not found", outages, key problems and registries that
    disclose the record's values (`disclose_values`) are never cached.
  * Each entry carries an HMAC (see ledger.cache_get), so a tampered database cannot plant a "verified".
  * An officer can always bypass it with "Ask the issuer again" (`fresh`).
  * Without PRAMANIK_FINGERPRINT_KEY there is no cache.
"""
from typing import Callable

from .. import config
from ..issuers.base import IssuerResult
from . import doctypes, ledger


def verify(query: Callable[[str, dict], IssuerResult], document_type: str, fields: dict, fresh: bool = False) -> dict:
    """Same result shape as the live lookup, plus `source` ("cache" or "live") and, for a hit, `age_seconds`."""
    cfg = config.cache()
    doc_type = doctypes.by_id(document_type)
    usable = (cfg["enabled"] and ledger.enabled() and doc_type is not None
              and all(fields.get(n) for n in doctypes.field_names(doc_type)))
    fp = ledger.content_fingerprint(doc_type, fields) if usable else None

    if usable and not fresh:
        hit = ledger.cache_get(fp)
        if hit:
            return {"reachable": True, "found": True, "status": hit["status"], "matches": hit["matches"], "values": {},
                    "error": "", "detail": "", "source": "cache", "age_seconds": hit["age_seconds"]}

    result = dict(query(document_type, fields))
    result["source"] = "live"
    if usable:
        if result["reachable"] and result["found"] and not result.get("values"):
            ledger.cache_put(fp, document_type, result["status"], result["matches"], cfg["ttl_seconds"])
        elif result["reachable"] and not result["found"]:
            ledger.cache_drop(fp)  # the issuer no longer knows it: forget any earlier answer
    return result
