"""Build the per-field rows and the coverage text for the response."""
from typing import Optional

NOT_FOUND = "not found"
NOT_QUERIED = "not queried"
UNREACHABLE = "unreachable"
MISMATCH = "does not match"  # the issuer says no; it does not reveal its own value


def field_rows(doc_type: Optional[dict], doc_fields: dict, issuer_result: Optional[dict], issuer_note: str) -> list:
    """One row per schema field, in schema order.

    - record found, field matches    -> issuer value = document value, match true
    - record found, field mismatches -> the issuer's value only if it chose to disclose it, else MISMATCH
    - otherwise                      -> issuer = issuer_note, match false
    """
    if doc_type is None:
        return []
    found = bool(issuer_result and issuer_result["reachable"] and issuer_result["found"])
    rows = []
    for spec in doc_type["fields"]:
        name = spec["name"]
        document = doc_fields.get(name) or ""
        if found:
            ok = bool(issuer_result["matches"].get(name, False))
            disclosed = (issuer_result.get("values") or {}).get(name)
            issuer = document if ok else (disclosed or MISMATCH)
        else:
            ok, issuer = False, issuer_note
        rows.append({"field": name, "label": spec.get("label", name),
                     "document": document, "issuer": issuer, "match": ok})
    return rows


def coverage(rows: list) -> str:
    if not rows:
        return "No printed fields confirmed with issuer"
    return f"{sum(1 for r in rows if r['match'])} of {len(rows)} printed fields confirmed with issuer"
