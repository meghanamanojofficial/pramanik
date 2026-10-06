"""Generate test PDFs from data/mock_records.json. Run from backend/:  python tools/make_test_pdfs.py

No record values are hard-coded here; everything comes from the records file.
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
RECORDS = ROOT / "data" / "mock_records.json"
OUT = ROOT.parent / "demo_docs" / "pdfs"

def make_pdf(path: Path, number: str, name: str, issue_date: str, income: str, qr_text: str) -> None:
    width, height = A4
    c = canvas.Canvas(str(path), pagesize=A4)
    lines = [
        ("STATE REVENUE DEPARTMENT", "Helvetica-Bold", 16),
        ("INCOME CERTIFICATE", "Helvetica-Bold", 14),
        (f"Certificate No: {number}", "Helvetica", 12),
        (f"Name: {name}", "Helvetica", 12),
        (f"Issue Date: {issue_date}", "Helvetica", 12),
        (f"Annual income: {income}", "Helvetica", 12),
    ]
    y = height - 90
    for text, font, size in lines:
        c.setFont(font, size)
        c.drawString(72, y, text)
        y -= 28

    img = qrcode.make(qr_text).convert("RGB")
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

    active = next((r for r in records if r.get("status") == "active"), None)
    if active is None:
        print("No active record in the records file; cannot build test PDFs.")
        return 1

    OUT.mkdir(exist_ok=True)
    n, name, d, inc = (active[k] for k in ("certificate_number", "holder_name", "issue_date", "income_amount"))

    make_pdf(OUT / "genuine.pdf", n, name, d, inc, n)
    make_pdf(OUT / "edited_amount.pdf", n, name, d, str(int(inc) + 100000), n)
    make_pdf(OUT / "unknown_number.pdf", "INC-9999-9999", name, d, inc, "INC-9999-9999")

    revoked = next((r for r in records if r.get("status") == "revoked"), None)
    revoked_path = OUT / "revoked.pdf"
    if revoked is not None:
        rn, rname, rd, rinc = (revoked[k] for k in ("certificate_number", "holder_name", "issue_date", "income_amount"))
        make_pdf(revoked_path, rn, rname, rd, rinc, rn)
    else:
        revoked_path.unlink(missing_ok=True)
        print("No revoked record; skipped revoked.pdf")

    print(f"Wrote test PDFs to {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
