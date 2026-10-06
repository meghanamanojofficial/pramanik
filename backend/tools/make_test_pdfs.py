"""Generate test PDFs from the records file and the document-type schema.
Run from backend/:  python tools/make_test_pdfs.py

Nothing is hard-coded here: the layout (header lines, labels, field order) comes from
config/document_types.json, the people and numbers from the issuer's records file, and the
test-case choices (which field to tamper with, the unknown number) from config/test_cases.json.

This script plays the issuing department's printer: it signs each genuine certificate's QR code with the
issuer's private key (issuer_service/signing_keys/, created by issuer_service/setup_keys.py). If there is no
key yet it falls back to plain-number QR codes and says so.

    genuine.pdf            signed QR, matches the record          -> VERIFIED
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
