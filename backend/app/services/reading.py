"""What a front-end (PDF text layer, or photo/scan OCR) hands to the shared verification flow."""
from dataclasses import dataclass, field
from typing import Optional

import numpy as np


@dataclass
class Reading:
    doc_type: Optional[dict] = None
    fields: dict = field(default_factory=dict)
    confidences: dict = field(default_factory=dict)   # per-field OCR confidence (images only)
    qr_raw: Optional[str] = None
    text: str = ""                                    # for the links check
    signals: list = field(default_factory=list)
    checks: dict = field(default_factory=dict)
    early: Optional[dict] = None                      # a verdict.early(...) decision: image cannot be judged
    rescan_guidance: Optional[str] = None
    page: Optional[np.ndarray] = None                 # rectified page, for the stamp check
