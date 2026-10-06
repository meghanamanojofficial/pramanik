"""Document-type schema loader. The schema lives in config/document_types.json;
nothing about field names, labels, patterns or document types is written in code.

Field spec keys used by the backend:
  name, label, value_pattern, normalize (list, optional)
The issuer service additionally uses `compare` (see issuer_service/core.py).
"""
import json
import os
import re
import unicodedata
from pathlib import Path
from typing import Optional

BACKEND_DIR = Path(__file__).resolve().parents[2]


def _config_path() -> Path:
    return Path(os.environ.get("DOCUMENT_TYPES_CONFIG", BACKEND_DIR / "config" / "document_types.json"))


def load_types() -> list:
    return json.loads(_config_path().read_text(encoding="utf-8"))["document_types"]


def by_id(type_id: str) -> Optional[dict]:
    return next((t for t in load_types() if t["id"] == type_id), None)


def detect(text: str, fuzzy_score: Optional[int] = None) -> Optional[dict]:
    """First document type whose `recognize` markers all appear in the text.

    `fuzzy_score` (0-100) lets OCR output with a misread letter or two still match: a marker counts as
    present when it is a substring or when its best partial match scores at least that much.
    """
    low = text.lower()

    def present(marker: str) -> bool:
        marker = marker.lower()
        if marker in low:
            return True
        if fuzzy_score is None:
            return False
        from rapidfuzz import fuzz
        return fuzz.partial_ratio(marker, low) >= fuzzy_score

    for dt in load_types():
        if all(present(m) for m in dt["recognize"]):
            return dt
    return None


def detect_by_key(value: Optional[str]) -> Optional[dict]:
    """Document type whose key field's value pattern matches `value` exactly (for example a QR payload).
    This is the schema-driven way to route by certificate series when the printed heading is unreadable."""
    if not value:
        return None
    for dt in load_types():
        spec = next(f for f in dt["fields"] if f["name"] == dt["key_field"])
        if re.fullmatch(spec["value_pattern"], value.strip()):
            return dt
    return None


def field_names(doc_type: dict) -> list:
    return [f["name"] for f in doc_type["fields"]]


def key_field(doc_type: dict) -> str:
    return doc_type["key_field"]


def field_pattern(spec: dict) -> "re.Pattern":
    """'<label>: <value>' with the value shape taken from the schema."""
    return re.compile(rf"{re.escape(spec['label'])}:\s*({spec['value_pattern']})", re.I | re.M)


def normalise(spec: dict, value: str) -> str:
    value = re.sub(r"\s+", " ", (value or "").strip())
    for op in spec.get("normalize", []):
        if op == "digits_only":
            value = re.sub(r"\D", "", value)
        else:
            raise ValueError(f"unknown normalize op: {op}")
    return value


# ---- comparison and OCR helpers (used for the QR's own signed fields and for scans) ----------------
def name_key(value) -> str:
    """Canonical personal name: case, punctuation, spacing and word order ignored; any changed letter is
    a different name. Mirrors issuer_service/core.py so a signed QR is judged by the same rule as the registry."""
    text = unicodedata.normalize("NFKC", "" if value is None else str(value)).casefold()
    text = re.sub(r"[^\w\s]", " ", text)
    return " ".join(sorted(text.split()))


def fields_match(spec: dict, a, b) -> bool:
    """Do two values of one field agree under the schema's `compare` rule?"""
    rule = spec.get("compare", {})
    method = rule.get("method", "exact")
    if method == "name":
        return name_key(a) == name_key(b)
    x, y = normalise(spec, a), normalise(spec, b)
    if rule.get("ignore_case"):
        x, y = x.lower(), y.lower()
    if method == "exact":
        return x == y
    if method == "fuzzy":
        from rapidfuzz import fuzz
        return fuzz.token_sort_ratio(x, y) >= rule.get("threshold", 97)
    raise ValueError(f"unknown compare method: {method}")


_CONFUSABLE = {"O": "0", "o": "0", "I": "1", "l": "1", "|": "1"}


def ocr_repair(value: str) -> str:
    """Fix the classic OCR letter/digit confusions, but only in whole tokens made *entirely* of confusable
    characters (so 'INC' and 'Holder' are left alone while 'OOOI' becomes '0001'). The caller must
    re-validate the result against the field's value_pattern; repair never makes a value valid by itself."""
    def fix(m: "re.Match") -> str:
        token = m.group(0)
        if len(token) >= 2 and all(c.isdigit() or c in _CONFUSABLE for c in token):
            return "".join(_CONFUSABLE.get(c, c) for c in token)
        return token
    return re.sub(r"[A-Za-z0-9|]+", fix, value)


def label_pattern(spec: dict) -> str:
    """Regex for a field label that tolerates OCR spacing and case, e.g. 'Annual  income'."""
    words = [re.escape(w) for w in spec["label"].split()]
    return r"(?<![A-Za-z])" + r"\s*".join(words)
