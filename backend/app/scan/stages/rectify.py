"""Find the page in a photo and flatten it (perspective correction)."""
import cv2
import numpy as np

from ... import config
from ...services.signals import Severity, Signal

MIN_SIDE = 400  # a "page" smaller than this is a false find (a box, a stamp), not the document


def _order(pts: np.ndarray) -> np.ndarray:
    rect = np.zeros((4, 2), dtype="float32")
    s = pts.sum(axis=1)
    rect[0], rect[2] = pts[np.argmin(s)], pts[np.argmax(s)]
    d = np.diff(pts, axis=1)
    rect[1], rect[3] = pts[np.argmin(d)], pts[np.argmax(d)]
    return rect


def rectify_page(img: np.ndarray) -> tuple[np.ndarray, list[Signal]]:
    """Returns (page image, signals). Falls back to the whole frame when no clear page outline exists
    (for example a flat scan that already fills the image)."""
    fallback = [Signal("rectify_fallback", Severity.OK, config.message("scan_rectify_fallback"))]
    if img is None:
        return img, fallback
    try:
        gray = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
        edged = cv2.Canny(cv2.GaussianBlur(gray, (5, 5), 0), 50, 200)
        contours, _ = cv2.findContours(edged, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
        for c in sorted(contours, key=cv2.contourArea, reverse=True)[:5]:
            approx = cv2.approxPolyDP(c, 0.02 * cv2.arcLength(c, True), True)
            if len(approx) == 4 and cv2.contourArea(approx) > img.shape[0] * img.shape[1] * 0.2:
                rect = _order(approx.reshape(4, 2).astype("float32"))
                tl, tr, br, bl = rect
                width = int(max(np.linalg.norm(br - bl), np.linalg.norm(tr - tl)))
                height = int(max(np.linalg.norm(tr - br), np.linalg.norm(tl - bl)))
                if width < MIN_SIDE or height < MIN_SIDE:
                    continue
                dst = np.array([[0, 0], [width - 1, 0], [width - 1, height - 1], [0, height - 1]], dtype="float32")
                warped = cv2.warpPerspective(img, cv2.getPerspectiveTransform(rect, dst), (width, height))
                return warped, [Signal("rectify_success", Severity.OK, config.message("scan_rectified"))]
    except Exception:
        pass
    return img, fallback
