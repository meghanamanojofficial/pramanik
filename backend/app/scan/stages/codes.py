"""Find the QR code in a photo: several regions, so a small code in a big image is still found."""
from typing import Optional

import cv2
import numpy as np

from ...services import qr_service


def _regions(img: np.ndarray):
    """(crop, x offset, y offset) for the corners (where certificates put their QR), then the whole page."""
    h, w = img.shape[:2]
    yield img[0:int(h * .45), int(w * .5):w], int(w * .5), 0
    yield img[0:int(h * .45), 0:int(w * .55)], 0, 0
    yield img[int(h * .55):h, int(w * .5):w], int(w * .5), int(h * .55)
    yield img[int(h * .55):h, 0:int(w * .55)], 0, int(h * .55)
    scale = min(1.0, 1400.0 / max(h, w))
    yield (cv2.resize(img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA) if scale < 1.0 else img), 0, 0


def _search(img: np.ndarray) -> Optional[tuple[str, Optional[tuple[int, int, int, int]]]]:
    if img is None or img.size == 0:
        return None
    h, w = img.shape[:2]
    scale = min(1.0, 1400.0 / max(h, w))
    for i, (crop, ox, oy) in enumerate(_regions(img)):
        hits = qr_service.decode_array(crop)
        if hits:
            hit = hits[0]
            if hit.box is None:
                return hit.data, None
            x0, y0, x1, y1 = hit.box
            k = 1.0 / scale if i == 4 else 1.0  # last region was downscaled; map its box back
            return hit.data, (int(x0 * k) + ox, int(y0 * k) + oy, int(x1 * k) + ox, int(y1 * k) + oy)
    return None


def find_qr(rectified: np.ndarray, original: np.ndarray) -> tuple[Optional[str], Optional[tuple[int, int, int, int]]]:
    """(payload, box). The box is in `rectified` coordinates (used to keep the QR out of the OCR), or None
    when the code was only found in the original frame."""
    found = _search(rectified)
    if found:
        return found
    if original is not rectified:
        found = _search(original)
        if found:
            return found[0], None
    return None, None
