"""PDF text, printed-field extraction and normalisation. Everything stays in memory."""
import re

import pymupdf as fitz  # PyMuPDF

FIELD_ORDER = ["certificate_number", "holder_name", "issue_date", "income_amount"]

_PATTERNS = {
    "certificate_number": re.compile(r"Certificate No:\s*(INC-\d{4}-\d{4})", re.I | re.M),
    "holder_name": re.compile(r"Name:\s*(.+)", re.I | re.M),
    "issue_date": re.compile(r"Issue Date:\s*(\d{4}-\d{2}-\d{2})", re.I | re.M),
    "income_amount": re.compile(r"Annual income:\s*([\d,]+)", re.I | re.M),
}


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
    except Exception as exc:  # corrupt file; never include details in the message
        raise UnreadablePDF from None


def normalise(field: str, value: str) -> str:
    value = re.sub(r"\s+", " ", value.strip())
    if field == "income_amount":
        value = re.sub(r"\D", "", value)
    return value


def extract_fields(text: str) -> dict[str, str | None]:
    """Return the four printed fields, or None for any that could not be read."""
    fields: dict[str, str | None] = {}
    for name in FIELD_ORDER:
        m = _PATTERNS[name].search(text)
        value = normalise(name, m.group(1)) if m else ""
        fields[name] = value or None
    return fields
