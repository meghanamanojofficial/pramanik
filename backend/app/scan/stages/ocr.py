"""OCR with Tesseract: per-word confidences, QR code masked out, optional second pass for cross-checking."""
import os
import shutil
from dataclasses import dataclass, field
from typing import Optional

import cv2
import numpy as np

from ... import config

_WINDOWS_PATHS = [r"C:\Program Files\Tesseract-OCR\tesseract.exe", r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe"]


class OcrUnavailable(Exception):
    """Tesseract is not installed (or not where we can find it)."""


@dataclass
class Word:
    text: str
    conf: float
    start: int  # offsets into Line.text
    end: int


@dataclass
class Line:
    text: str
    words: list[Word] = field(default_factory=list)


@dataclass
class OcrPass:
    name: str
    lines: list[Line]
    mean_conf: float

    @property
    def text(self) -> str:
        return "\n".join(line.text for line in self.lines)


def _configure():
    import pytesseract

    cmd = (os.environ.get("TESSERACT_CMD") or config.scan()["ocr"]["tesseract_cmd"] or shutil.which("tesseract")
           or next((p for p in _WINDOWS_PATHS if os.path.exists(p)), None))
    if not cmd:
        raise OcrUnavailable
    pytesseract.pytesseract.tesseract_cmd = cmd
    return pytesseract


def available() -> bool:
    try:
        _configure()
        return True
    except (OcrUnavailable, ImportError):
        return False


def prepare(img: np.ndarray, mask_box: Optional[tuple[int, int, int, int]] = None) -> tuple[np.ndarray, np.ndarray]:
    """(grayscale, binarised) copies ready for OCR. The QR block is painted white first: it is not text,
    and its noise otherwise leaks into neighbouring lines and drags the confidence down."""
    work = img.copy()
    if mask_box:
        x0, y0, x1, y1 = mask_box
        pad = int(0.12 * max(x1 - x0, y1 - y0))
        work[max(0, y0 - pad):y1 + pad, max(0, x0 - pad):x1 + pad] = 255
    h, w = work.shape[:2]
    scale = min(1.0, config.scan()["ocr"]["max_dimension"] / max(h, w))
    if scale < 1.0:
        work = cv2.resize(work, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
    gray = cv2.cvtColor(work, cv2.COLOR_RGB2GRAY)
    enhanced = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(gray)
    _, binary = cv2.threshold(enhanced, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return gray, binary


def run(image: np.ndarray, psm: int, name: str) -> OcrPass:
    """One Tesseract pass, grouped into lines of words that each carry their own confidence."""
    pytesseract = _configure()
    data = pytesseract.image_to_data(image, config=f"--psm {psm}", output_type=pytesseract.Output.DICT)
    grouped: dict[tuple, list[tuple[str, float]]] = {}
    for i, text in enumerate(data["text"]):
        text = (text or "").strip()
        try:
            conf = float(data["conf"][i])
        except (TypeError, ValueError):
            conf = -1.0
        if text and conf >= 0:
            grouped.setdefault((data["block_num"][i], data["par_num"][i], data["line_num"][i]), []).append((text, conf))

    lines, confs = [], []
    for key in sorted(grouped):
        line, pos = Line(""), 0
        for text, conf in grouped[key]:
            if line.text:
                line.text += " "
                pos += 1
            line.words.append(Word(text, conf, pos, pos + len(text)))
            line.text += text
            pos += len(text)
            confs.append(conf)
        lines.append(line)
    return OcrPass(name, lines, float(np.mean(confs)) if confs else 0.0)
