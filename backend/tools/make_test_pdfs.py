"""Generate test PDFs from the records file and the document-type schema.
Run from backend/:  python tools/make_test_pdfs.py

Nothing is hard-coded here: the layout (header lines, labels, field order) comes from
config/document_types.json, the people and numbers from the issuer's records file, and the
test-case choices (which field to tamper with, the unknown number) from config/test_cases.json.

This script plays the issuing department's printer: it signs each genuine certificate's QR code with the
issuer's private key (issuer_service/signing_keys/, created by issuer_service/setup_keys.py). If there is no
key yet it falls back to plain-number QR codes and says so.

    genuine.pdf            signed QR, matches the record          -> VERIFIED
    painted_over_amount.pdf   a new amount painted over the old one; the old text is still in the file -> MISMATCH
    hidden_text_forgery.pdf   a picture of an edited page with invisible genuine text -> MISMATCH
    edited_amount.pdf      amount edited; QR is the genuine signature (so it disagrees with the print) -> MISMATCH
    unknown_number.pdf     number the issuer never issued, plain QR (a forger has no key) -> SUSPICIOUS
    revoked.pdf            signed QR of a revoked record           -> SUSPICIOUS
    forged_signature.pdf   matches the record, but the QR signature is wrong -> MATCHES_RECORD_INTEGRITY_CONCERNS
    plain_qr.pdf           matches the record, older plain-number QR -> VERIFIED
"""
import io
import json
import sys
from pathlib import Path

import pymupdf as fitz
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

sys.path.insert(0, str(ROOT.parent / "issuer_service"))
import signing  # noqa: E402  (the issuer's signer)


def signed_qr(values: dict) -> str | None:
    """The issuer-signed token for a record, or None if no signing key exists yet."""
    try:
        return signing.issue_token(DOC["issuer_id"], DOC["id"], {f["name"]: str(values[f["name"]]) for f in DOC["fields"]})
    except FileNotFoundError:
        return None


def broken_signature(token: str) -> str:
    """Same payload, signature replaced: what someone who copied a real QR and edited it would have."""
    payload, sig = token.split(".")
    return payload + "." + ("A" if sig[0] != "A" else "B") + sig[1:]


def make_pdf(path: Path, values: dict, qr_text: str | None = None) -> None:
    width, height = A4
    c = canvas.Canvas(str(path), pagesize=A4)
    lines = [(text, "Helvetica-Bold", 16 if i == 0 else 14) for i, text in enumerate(DOC["header_lines"])]
    lines += [(f"{f['label']}: {values[f['name']]}", "Helvetica", 12) for f in DOC["fields"]]
    y = height - 90
    for text, font, size in lines:
        c.setFont(font, size)
        c.drawString(72, y, text)
        y -= 28

    img = qrcode.make(qr_text if qr_text is not None else values[KEY]).convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    c.drawImage(ImageReader(buf), width - 72 - 130, height - 90 - 110, 130, 130)
    c.showPage()
    c.save()


def painted_over(genuine: Path, out: Path) -> None:
    """The forgery a PDF editor that only paints produces: new number on a white box, old text still underneath."""
    with fitz.open(str(genuine)) as doc:
        page, tamper = doc[0], CFG["tamper"]
        spec = next(f for f in DOC["fields"] if f["name"] == tamper["field"])
        old = next(l for l in page.get_text().splitlines() if l.startswith(spec["label"]))
        rect = page.search_for(old)[0]
        new = f"{spec['label']}: {int(old.split(': ')[1]) + tamper['increase']}"
        page.draw_rect(rect + (-2, -2, 60, 2), color=None, fill=(1, 1, 1))
        page.insert_text((rect.x0, rect.y1 - 2), new, fontsize=12)
        doc.save(str(out))


def hidden_text(genuine: Path, painted: Path, out: Path) -> None:
    """A picture of the edited page, with an invisible text layer that still says the genuine values."""
    with fitz.open(str(painted)) as edited, fitz.open(str(genuine)) as real, fitz.open() as doc:
        shown = edited[0].get_pixmap(dpi=200, alpha=False).tobytes("jpeg", jpg_quality=85)
        page = doc.new_page(width=edited[0].rect.width, height=edited[0].rect.height)
        page.insert_image(page.rect, stream=shown)
        for block in real[0].get_text("dict")["blocks"]:
            for line in block.get("lines", []):
                text = "".join(span["text"] for span in line["spans"])
                if text.strip():
                    page.insert_text((line["bbox"][0], line["bbox"][3] - 2), text, fontsize=12, render_mode=3)
        doc.save(str(out))


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

    token = signed_qr(active)  # None: no signing key yet, so every QR below is the plain number
    if token is None:
        print("No signing key found (run python issuer_service/setup_keys.py): using plain-number QR codes.")

    make_pdf(OUT / "genuine.pdf", active, token)
    make_pdf(OUT / "edited_amount.pdf", {**active, tamper["field"]: str(int(active[tamper["field"]]) + tamper["increase"])}, token)
    make_pdf(OUT / "unknown_number.pdf", {**active, KEY: CFG["unknown_key_value"]})
    make_pdf(OUT / "plain_qr.pdf", active)
    forged = OUT / "forged_signature.pdf"
    if token:
        make_pdf(forged, active, broken_signature(token))
    else:
        forged.unlink(missing_ok=True)

    painted_over(OUT / "genuine.pdf", OUT / "painted_over_amount.pdf")
    hidden_text(OUT / "genuine.pdf", OUT / "painted_over_amount.pdf", OUT / "hidden_text_forgery.pdf")

    revoked = next((r for r in records if r.get("status") == "revoked"), None)
    revoked_path = OUT / "revoked.pdf"
    if revoked is not None:
        make_pdf(revoked_path, revoked, signed_qr(revoked))
    else:
        revoked_path.unlink(missing_ok=True)
        print("No revoked record; skipped revoked.pdf")

    print(f"Wrote test PDFs to {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
