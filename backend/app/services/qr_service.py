"""Decode the QR on page 1, in memory. Returns the encoded text or None."""
import cv2
import pymupdf as fitz  # PyMuPDF
import numpy as np


def _render_page_one(raw: bytes) -> np.ndarray | None:
    try:
        with fitz.open(stream=raw, filetype="pdf") as doc:
            if doc.page_count == 0:
                return None
            pix = doc[0].get_pixmap(dpi=200)
            img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
            return img.copy()
    except Exception:
        return None


def decode_qr(raw: bytes) -> str | None:
    img = _render_page_one(raw)
    if img is None:
        return None
    gray = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY) if img.shape[2] >= 3 else img[:, :, 0]

    try:
        text, _, _ = cv2.QRCodeDetector().detectAndDecode(gray)
        if text:
            return text.strip()
    except Exception:
        pass

    try:  # fallback; needs the zbar system library
        from pyzbar.pyzbar import decode

        results = decode(gray)
        if results:
            return results[0].data.decode("utf-8", errors="ignore").strip() or None
    except Exception:
        pass
    return None
