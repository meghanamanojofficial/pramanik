"""Quality gate: is this image good enough to read? Thresholds come from config/scan.json.

Exposure is judged from the paper level and the ink contrast, not the mean brightness: a clean white page
legitimately averages ~250, which the old mean-based test mistook for glare.
"""
import io
import os

import cv2
import numpy as np
from PIL import Image, ImageOps

from ... import config
from ...services.signals import Severity, Signal


def load_image(raw: bytes) -> tuple[np.ndarray | None, Signal | None]:
    """Decode to an upright RGB array (phone photos carry their rotation in EXIF), or explain why not."""
    cfg = config.scan()
    try:
        pil = Image.open(io.BytesIO(raw))
        if pil.width * pil.height > cfg["max_image_pixels"]:
            raise ValueError("too many pixels")
        side = int(os.environ.get("PRAMANIK_MAX_IMAGE_SIDE") or cfg.get("max_image_side", 3000))
        if max(pil.size) > side:
            pil.draft("RGB", (side, side))   # JPEG: decode at a reduced scale, so a 12 MP photo never fills memory
        pil = ImageOps.exif_transpose(pil)   # phone photos carry their rotation in EXIF
        if max(pil.size) > side:             # OCR reads at most 2400 px anyway (config ocr.max_dimension)
            pil.thumbnail((side, side), Image.LANCZOS)
        pil = pil.convert("RGB")
        img = np.array(pil)
        if img.size == 0:
            raise ValueError("empty")
        return img, None
    except Exception:  # corrupt, truncated, oversize, or not an image at all
        return None, Signal("quality_invalid_image", Severity.FAIL, config.message("scan_invalid_image"))


def check_quality(raw: bytes) -> tuple[list[Signal], np.ndarray | None]:
    img, problem = load_image(raw)
    if problem:
        return [problem], None
    return assess(img), img


def assess(img: np.ndarray) -> list[Signal]:
    q = config.scan()["quality"]
    signals: list[Signal] = []
    h, w = img.shape[:2]
    if w < q["min_width"] or h < q["min_height"]:
        signals.append(Signal("quality_low_resolution", Severity.FAIL, config.message("scan_low_resolution", w=w, h=h)))

    gray = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
    scale = min(1.0, 800.0 / max(h, w))
    small = cv2.resize(gray, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA) if scale < 1.0 else gray

    ink, paper = (float(v) for v in np.percentile(small, [0.5, 95]))
    dark = paper < q["paper_brightness_min"]
    # A dark image has a flat Laplacian too, so exposure is judged first and blur only on a lit image.
    blurry = (not dark) and float(cv2.Laplacian(small, cv2.CV_32F).var()) < q["blur_laplacian_min"]
    if dark:
        signals.append(Signal("quality_dark", Severity.FAIL, config.message("scan_dark")))
    elif blurry:
        signals.append(Signal("quality_blur", Severity.FAIL, config.message("scan_blur")))
    elif paper - ink < q["ink_contrast_min"]:
        signals.append(Signal("quality_glare", Severity.FAIL, config.message("scan_glare")))  # washed out
    elif float(np.median(small)) < q["glare_paper_median_max"] and float((small >= 250).mean()) > q["glare_saturated_fraction"]:
        signals.append(Signal("quality_glare", Severity.FAIL, config.message("scan_glare")))  # flash hot-spot

    if not signals:
        signals.append(Signal("quality_ok", Severity.OK, config.message("scan_quality_ok")))
    return signals
