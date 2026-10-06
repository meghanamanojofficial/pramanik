"""Does the PDF's text layer say what the page shows?

A text PDF can carry text that is not what a person sees (painted-over values, invisible text). The verdict is
built from the text layer, so it is compared here with an OCR reading of the rendered page. Only a *confident*
disagreement is an accusation; a page OCR cannot read gives a mild note, never a false alarm.
"""
from typing import Optional

import numpy as np

from .. import config
from ..scan import pipeline
from ..scan.stages import codes, ocr, parse
from ..services import doctypes
from ..services.signals import Severity, Signal


def check(doc_type: Optional[dict], fields: dict, page: Optional[np.ndarray]) -> list[Signal]:
    if doc_type is None or page is None or not config.scan()["pdf_visual_check"]["enabled"] or not ocr.available():
        return []
    floor = config.scan()["ocr"]["field_confidence_min"]
    with pipeline.slot():  # shares the cap on simultaneous OCR with photo scans
        _, box = codes.find_qr(page, page)
        gray, _ = ocr.prepare(page, box)
        seen = parse.read_fields(doc_type, ocr.run(gray, 6, "page_view"))

    signals, unconfirmed = [], 0
    for spec in doc_type["fields"]:
        name, read = spec["name"], seen.get(spec["name"])
        if read is None or read.conf < floor:
            unconfirmed += 1
        elif not doctypes.fields_match(spec, fields.get(name), read.value):
            signals.append(Signal("pdf_text_differs_from_page", Severity.FAIL,
                                  config.message("visual_mismatch", field=name), region=name))
    if not signals:
        signals.append(Signal("pdf_visual_unconfirmed", Severity.WEAK, config.message("visual_unconfirmed")) if unconfirmed
                       else Signal("pdf_visual_confirmed", Severity.OK, config.message("visual_confirmed")))
    return signals
