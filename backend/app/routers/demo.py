"""Sample documents for a public demo. Off unless PRAMANIK_DEMO=1.

Demo certificates carry QR codes signed with THIS installation's key, so ones made on another machine would show
as forged here. A demo deployment therefore makes its own (see run_all.py) and offers them for download, to signed-in
users only, from a fixed list: nothing else on disk can be requested.
"""
import html
import os

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response

from .. import config, security

router = APIRouter()
DEMO_DIR = config.BACKEND_DIR.parent / "demo_docs"

# (folder, file, what it is, expected verdict code)
CATALOG = [
    ("pdfs", "genuine.pdf", "A genuine certificate", "VERIFIED"),
    ("scans", "genuine_photographed.jpg", "A skewed phone photo of the genuine certificate", "VERIFIED"),
    ("scans", "genuine_clean.jpg", "A flat scan of the genuine certificate", "VERIFIED"),
    ("scans", "genuine_phone_rotated.jpg", "A phone photo stored sideways (EXIF rotation)", "VERIFIED"),
    ("pdfs", "scanned_genuine.pdf", "The genuine certificate as a picture-only PDF (read by OCR)", "VERIFIED"),
    ("pdfs", "plain_qr.pdf", "Genuine, with an older plain-number QR code", "VERIFIED"),
    ("pdfs", "edited_amount.pdf", "The income amount was edited", "MISMATCH"),
    ("pdfs", "painted_over_amount.pdf", "A new amount painted over the old one (old text still hidden underneath)", "MISMATCH"),
    ("pdfs", "hidden_text_forgery.pdf", "A picture of an edited page with invisible genuine text on top", "MISMATCH"),
    ("pdfs", "hostile_name.pdf", "The name field contains HTML (it must be shown as plain text)", "MISMATCH"),
    ("scans", "tampered_amount.jpg", "A photo of the edited certificate", "MISMATCH"),
    ("pdfs", "forged_signature.pdf", "Matches the record, but the QR signature is forged", "MATCHES_RECORD_INTEGRITY_CONCERNS"),
    ("scans", "forged_signature.jpg", "A photo of the forged-signature certificate", "MATCHES_RECORD_INTEGRITY_CONCERNS"),
    ("pdfs", "unknown_number.pdf", "A certificate number the issuer never issued", "SUSPICIOUS"),
    ("scans", "unknown_number.jpg", "A photo of the never-issued certificate", "SUSPICIOUS"),
    ("pdfs", "revoked.pdf", "A certificate the issuer has revoked", "SUSPICIOUS"),
    ("scans", "revoked.jpg", "A photo of the revoked certificate", "SUSPICIOUS"),
    ("scans", "genuine_blurry.jpg", "Too blurry to read", "RESCAN"),
    ("scans", "genuine_dark.jpg", "Too dark to read", "RESCAN"),
    ("scans", "unreadable_noise.jpg", "Noisy: read, but not reliably", "INCONCLUSIVE"),
]
_BY_NAME = {name: (folder, name) for folder, name, _, _ in CATALOG}


def enabled() -> bool:
    config.load_env()
    return os.environ.get("PRAMANIK_DEMO") == "1"


def _gate(request: Request):
    """None when allowed; otherwise the response to send instead."""
    if not enabled():
        return Response(status_code=404)
    user = security.current_user(request)
    if user is None or not user.profile_complete:
        return RedirectResponse("/app/signin.html", status_code=303, headers={"Cache-Control": "no-store"})
    return None


@router.get("/demo", include_in_schema=False)
def demo_page(request: Request):
    blocked = _gate(request)
    if blocked is not None:
        return blocked
    labels = config.load()["verdict_labels"]
    rows = []
    for folder, name, what, verdict in CATALOG:
        if (DEMO_DIR / folder / name).exists():
            rows.append(f'<tr><td><a href="/demo/files/{html.escape(name)}" download>{html.escape(name)}</a></td>'
                        f"<td>{html.escape(what)}</td><td>{html.escape(labels.get(verdict, verdict))}</td></tr>")
    body = ("<!doctype html><html lang=en><head><meta charset=utf-8><title>Sample documents</title>"
            "<meta name=viewport content='width=device-width,initial-scale=1'>"
            "<style>body{font:15px/1.5 system-ui,sans-serif;max-width:60rem;margin:2rem auto;padding:0 1rem;background:#0d0f14;color:#e6e8ee}"
            "a{color:#8fb4ff}table{border-collapse:collapse;width:100%}td,th{padding:.5rem .6rem;border-bottom:1px solid #262a35;text-align:left;vertical-align:top}"
            "th{color:#9aa3b5;font-weight:600}.n{color:#9aa3b5}</style></head><body>"
            "<h1>Sample documents</h1>"
            "<p class=n>Made on this server, so their QR signatures are valid here. Download one, then upload it on the "
            "<a href='/app/maindash.html'>dashboard</a>. The last column is what the check should say. Using the same genuine "
            "certificate under many different case IDs correctly raises a reuse warning.</p>"
            "<table><tr><th>File</th><th>What it is</th><th>Expected result</th></tr>" + "".join(rows) + "</table>"
            + ("" if rows else "<p>The sample documents are still being prepared (this takes a minute after the server starts). Reload this page shortly.</p>") + "</body></html>")
    return HTMLResponse(body, headers={"Cache-Control": "no-store", "Content-Security-Policy": security.CSP_APP})


@router.get("/demo/files/{name}", include_in_schema=False)
def demo_file(name: str, request: Request):
    blocked = _gate(request)
    if blocked is not None:
        return blocked
    entry = _BY_NAME.get(name)  # only names on the list: never a path the caller made up
    path = DEMO_DIR / entry[0] / entry[1] if entry else None
    if path is None or not path.is_file():
        return Response(status_code=404)
    return FileResponse(path, filename=name, headers={"Cache-Control": "no-store"})
