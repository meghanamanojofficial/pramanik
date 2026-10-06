"""One certificate presented in many cases, or one stamp pasted onto different certificates."""
from typing import Optional

import numpy as np

from .. import config
from ..services import ledger
from ..services.signals import Severity, Signal


def stamp_hash(img: Optional[np.ndarray], doc_type: dict) -> Optional[str]:
    """Perceptual hash of the seal/stamp area, or None. The area comes from the document type's optional
    `stamp_region` ([x0, y0, x1, y1] as fractions of the page). No region, or a region that is mostly blank
    paper, gives None: a blank patch is not a stamp and would look 'identical' on every certificate."""
    region = doc_type.get("stamp_region")
    if img is None or not region:
        return None
    try:
        import imagehash
        from PIL import Image

        h, w = img.shape[:2]
        x0, y0, x1, y1 = region
        crop = img[int(h * y0):int(h * y1), int(w * x0):int(w * x1)]
        gray = np.asarray(Image.fromarray(crop).convert("L"))
        if (gray < 128).mean() < config.scan()["reuse"]["stamp_min_ink_fraction"]:
            return None
        return str(imagehash.phash(Image.fromarray(gray), hash_size=8))
    except Exception:
        return None


def hamming(a: str, b: str) -> int:
    return bin(int(a, 16) ^ int(b, 16)).count("1")


def check(doc_type: Optional[dict], fields: dict, case_id: str, input_type: str,
          stamp: Optional[str]) -> list[Signal]:
    cfg = config.scan()["reuse"]
    if doc_type is None or not ledger.enabled() or input_type not in _kinds(cfg):
        return []
    signals: list[Signal] = []
    try:
        fp, case_fp = ledger.content_fingerprint(doc_type, fields), ledger.case_fingerprint(case_id)
        others = ledger.other_case_count(fp, case_fp)
        if others >= cfg["strong_from_other_cases"]:
            signals.append(Signal("duplicate_scan_excessive", Severity.STRONG, config.message("reuse_many", count=others)))
        elif others >= cfg["warn_from_other_cases"]:
            signals.append(Signal("duplicate_scan_prior", Severity.WEAK, config.message("reuse_other_cases", count=others)))
        if stamp:
            if any(hamming(stamp, prior) <= cfg["stamp_hamming_max"] for prior, _ in ledger.stamp_hashes(fp)):
                signals.append(Signal("stamp_reuse_detected", Severity.STRONG, config.message("stamp_reuse")))
    except Exception:
        return []  # a ledger problem never changes what the officer is told about the document
    return signals


def _kinds(cfg: dict) -> set:
    """`input_type` is pdf / scan / scanned_pdf; config says 'pdf' or 'scan' for the family."""
    kinds = set()
    if "pdf" in cfg["applies_to"]:
        kinds.add("pdf")
    if "scan" in cfg["applies_to"]:
        kinds.update({"scan", "scanned_pdf"})
    return kinds
