"""Build the per-field rows and the coverage text for the response."""
from .extract import FIELD_ORDER

NOT_FOUND = "not found"
NOT_QUERIED = "not queried"
UNREACHABLE = "unreachable"


def field_rows(doc_fields: dict, issuer_result: dict | None, issuer_note: str) -> list[dict]:
    """One row per template field, always in FIELD_ORDER.

    - record found, field matches    -> issuer value = document value, match true
    - record found, field mismatches -> issuer's own value, match false
    - otherwise                      -> issuer = issuer_note, match false
    """
    rows = []
    found = bool(issuer_result and issuer_result["reachable"] and issuer_result["found"])
    for name in FIELD_ORDER:
        document = doc_fields.get(name) or ""
        if found:
            ok = bool(issuer_result["matches"].get(name, False))
            issuer = document if ok else issuer_result["values"].get(name, "")
        else:
            ok, issuer = False, issuer_note
        rows.append({"field": name, "document": document, "issuer": issuer, "match": ok})
    return rows


def coverage(rows: list[dict]) -> str:
    return f"{sum(1 for r in rows if r['match'])} of 4 printed fields confirmed with issuer"
