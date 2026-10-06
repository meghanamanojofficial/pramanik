"""Generate test PDFs from the records file and the document-type schema.
Run from backend/:  python tools/make_test_pdfs.py

Nothing is hard-coded here: the layout (header lines, labels, field order) comes from
config/document_types.json, the people and numbers from data/mock_records.json, and the
test-case choices (which field to tamper with, the unknown number) from config/test_cases.json.
"""
import io
import json
import sys
from pathlib import Path

import qrcode
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

ROOT = Path(__file__).resolve().parents[1]
CFG = json.loads((ROOT / "config" / "test_cases.json").read_text(encoding="utf-8"))
SCHEMA = json.loads((ROOT / "config" / "document_types.json").read_text(encoding="utf-8"))["document_types"]
DOC = next(t for t in SCHEMA if t["id"] == CFG["document_type"])
RECORDS = ROOT / CFG["records_file"]
OUT = ROOT.parent / "demo_docs" / "pdfs"
KEY = DOC["key_field"]


def make_pdf(path: Path, values: dict) -> None:
    width, height = A4
    c = canvas.Canvas(str(path), pagesize=A4)
    lines = [(text, "Helvetica-Bold", 16 if i == 0 else 14) for i, text in enumerate(DOC["header_lines"])]
    lines += [(f"{f['label']}: {values[f['name']]}", "Helvetica", 12) for f in DOC["fields"]]
    y = height - 90
    for text, font, size in lines:
        c.setFont(font, size)
        c.drawString(72, y, text)
        y -= 28

    img = qrcode.make(values[KEY]).convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    c.drawImage(ImageReader(buf), width - 72 - 130, height - 90 - 110, 130, 130)
    c.showPage()
    c.save()


def main() -> int:
    try:
        records = json.loads(RECORDS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        print(f"Cannot read {RECORDS}")
        return 1

    if any(r.get(KEY) == CFG["unknown_key_value"] for r in records):
        print(f'{CFG["unknown_key_value"]} exists in the records file; change unknown_key_value in config/test_cases.json.')
        return 1

    active = next((r for r in records if r.get("status") == "active"), None)
    if active is None:
        print("No active record in the records file; cannot build test PDFs.")
        return 1

    OUT.mkdir(parents=True, exist_ok=True)
    tamper = CFG["tamper"]

    make_pdf(OUT / "genuine.pdf", active)
    make_pdf(OUT / "edited_amount.pdf", {**active, tamper["field"]: str(int(active[tamper["field"]]) + tamper["increase"])})
    make_pdf(OUT / "unknown_number.pdf", {**active, KEY: CFG["unknown_key_value"]})

    revoked = next((r for r in records if r.get("status") == "revoked"), None)
    revoked_path = OUT / "revoked.pdf"
    if revoked is not None:
        make_pdf(revoked_path, revoked)
    else:
        revoked_path.unlink(missing_ok=True)
        print("No revoked record; skipped revoked.pdf")

    print(f"Wrote test PDFs to {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
