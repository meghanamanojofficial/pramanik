"""PDF text and printed-field extraction. Which fields exist comes from the document-type schema.
Everything stays in memory."""
from typing import Optional

import pymupdf as fitz  # PyMuPDF

from .doctypes import field_pattern, normalise


class UnreadablePDF(Exception):
    pass


def extract_text(raw: bytes) -> str:
    try:
        with fitz.open(stream=raw, filetype="pdf") as doc:
            if doc.needs_pass:
                raise UnreadablePDF
            return "\n".join(page.get_text() for page in doc)
    except UnreadablePDF:
        raise
    except Exception:  # corrupt file; never include details in the message
        raise UnreadablePDF from None


def extract_fields(text: str, doc_type: dict) -> dict[str, Optional[str]]:
    """Return every field the schema lists for this document type, or None for any that could not be read."""
    fields: dict[str, Optional[str]] = {}
    for spec in doc_type["fields"]:
        m = field_pattern(spec).search(text)
        value = normalise(spec, m.group(1)) if m else ""
        fields[spec["name"]] = value or None
    return fields
