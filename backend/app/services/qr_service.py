"""Decode QR codes in memory. Used for page 1 of a PDF and for every region of a photo or scan."""
from dataclasses import dataclass
from typing import Optional

import cv2
import pymupdf as fitz  # PyMuPDF
import numpy as np


@dataclass
class QRHit:
    data: str
    box: Optional[tuple[int, int, int, int]] = None  # x0, y0, x1, y1 in the array that was searched


def render_page_one(raw: bytes, dpi: int = 200) -> np.ndarray | None:
    """Page 1 of a PDF as an RGB array, or None."""
    try:
        with fitz.open(stream=raw, filetype="pdf") as doc:
            if doc.page_count == 0:
                return None
            pix = doc[0].get_pixmap(dpi=dpi, alpha=False)
            img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
            return img.copy()
    except Exception:
        return None


def _to_gray(img: np.ndarray) -> np.ndarray:
    if img.ndim == 2:
        return img
    return cv2.cvtColor(img, cv2.COLOR_RGB2GRAY) if img.shape[2] >= 3 else img[:, :, 0]


def _box(points) -> Optional[tuple[int, int, int, int]]:
    try:
        pts = np.asarray(points, dtype=float).reshape(-1, 2)
        return int(pts[:, 0].min()), int(pts[:, 1].min()), int(pts[:, 0].max()), int(pts[:, 1].max())
    except Exception:
        return None


def decode_array(img: np.ndarray) -> list[QRHit]:
    """Every QR code found in an image array (OpenCV first, then zbar if installed)."""
    if img is None or img.size == 0:
        return []
    gray = _to_gray(img)
    hits: list[QRHit] = []

    try:
        text, points, _ = cv2.QRCodeDetector().detectAndDecode(gray)
        if text and text.strip():
            hits.append(QRHit(text.strip(), _box(points) if points is not None else None))
    except Exception:
        pass

    try:  # fallback; needs the zbar system library
        from pyzbar.pyzbar import decode

        for item in decode(gray):
            if item.type != "QRCODE":
                continue
            data = item.data.decode("utf-8", errors="ignore").strip()
            if data and not any(h.data == data for h in hits):
                r = item.rect
                hits.append(QRHit(data, (r.left, r.top, r.left + r.width, r.top + r.height)))
    except Exception:
        pass
    return hits


def decode_qr(raw: bytes) -> str | None:
    """The text of the first QR code on page 1 of a PDF, or None."""
    img = render_page_one(raw)
    hits = decode_array(img) if img is not None else []
    return hits[0].data if hits else None
