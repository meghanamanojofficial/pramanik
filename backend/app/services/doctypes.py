"""Document-type schema loader. The schema lives in config/document_types.json;
nothing about field names, labels, patterns or document types is written in code.

Field spec keys used by the backend:
  name, label, value_pattern, normalize (list, optional)
The issuer service additionally uses `compare` (see issuer_service/core.py).
"""
import json
import os
import re
from pathlib import Path
from typing import Optional

BACKEND_DIR = Path(__file__).resolve().parents[2]


def _config_path() -> Path:
    return Path(os.environ.get("DOCUMENT_TYPES_CONFIG", BACKEND_DIR / "config" / "document_types.json"))


def load_types() -> list:
    return json.loads(_config_path().read_text(encoding="utf-8"))["document_types"]


def detect(text: str) -> Optional[dict]:
    """First document type whose `recognize` markers all appear in the text."""
    low = text.lower()
    for dt in load_types():
        if all(marker.lower() in low for marker in dt["recognize"]):
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
