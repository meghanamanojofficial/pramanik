"""Read the schema's fields out of OCR lines. Which fields exist, their labels and value shapes all come
from config/document_types.json, exactly as for text PDFs; this only adds OCR tolerance (label spacing,
letter/digit confusions) and a confidence for every value."""
import re
from dataclasses import dataclass
from typing import Optional

from ... import config
from ...services import doctypes
from .ocr import Line, OcrPass

_SEP = r"\s*[:;.\-]?\s*"


@dataclass
class FieldRead:
    value: str
    conf: float


def detect_doc_type(text: str, qr_number: Optional[str]) -> Optional[dict]:
    """Heading first (tolerating misread letters), then the QR's number, then a certificate-number pattern
    anywhere in the text. All of it comes from the schema."""
    dt = doctypes.detect(text, fuzzy_score=config.scan()["ocr"]["type_match_score"]) or doctypes.detect_by_key(qr_number)
    if dt:
        return dt
    fixed = doctypes.ocr_repair(text)
    for cand in doctypes.load_types():
        spec = next(f for f in cand["fields"] if f["name"] == cand["key_field"])
        if re.search(spec["value_pattern"], fixed):
            return cand
    return None


def _match(spec: dict, rest: str) -> Optional[re.Match]:
    """Value at the start of `rest`. Fields marked `ocr_repair` get their O/0 and I/1 confusions fixed
    *first*: a prefix match on the raw text would otherwise accept a truncated value ('1OOOOO' -> '1').
    Repair is a no-op on text that is already clean."""
    return re.match(spec["value_pattern"], doctypes.ocr_repair(rest) if spec.get("ocr_repair") else rest)


def _conf(line: Line, start: int, end: int) -> float:
    confs = [w.conf for w in line.words if w.start < end and w.end > start]
    return sum(confs) / len(confs) if confs else 0.0


def _read_one(spec: dict, lines: list[Line], key_field: bool) -> Optional[FieldRead]:
    label = re.compile(doctypes.label_pattern(spec) + _SEP, re.I)
    for line in lines:
        m = label.search(line.text)
        if not m:
            continue
        rest = line.text[m.end():]
        v = _match(spec, rest)
        if v is None:
            continue
        raw = v.group(0)
        value = doctypes.normalise(spec, raw)
        if value:
            return FieldRead(value, _conf(line, m.end(), m.end() + v.end()))
    if key_field:  # the certificate number is distinctive enough to find without its label
        for line in lines:
            fixed = doctypes.ocr_repair(line.text) if spec.get("ocr_repair") else line.text
            v = re.search(spec["value_pattern"], fixed)
            if v:
                return FieldRead(doctypes.normalise(spec, v.group(0)), _conf(line, v.start(), v.end()))
    return None


def read_fields(doc_type: dict, ocr_pass: OcrPass) -> dict[str, FieldRead]:
    out = {}
    for spec in doc_type["fields"]:
        r = _read_one(spec, ocr_pass.lines, spec["name"] == doc_type["key_field"])
        if r:
            out[spec["name"]] = r
    return out


def reconcile(doc_type: dict, reads: list[dict[str, FieldRead]]) -> tuple[dict, dict, dict]:
    """Merge one or more OCR passes into (values, confidences, problems).

    problems maps field -> "missing" | "low" | "inconsistent":
      missing       no pass found it
      low           the best reading is below field_confidence_min
      inconsistent  two passes both read it confidently and disagree (never resolved by guessing)
    """
    floor = config.scan()["ocr"]["field_confidence_min"]
    values, confs, problems = {}, {}, {}
    for spec in doc_type["fields"]:
        name = spec["name"]
        cands = [r[name] for r in reads if name in r]
        if not cands:
            values[name], problems[name] = None, "missing"
            continue
        sure = [c for c in cands if c.conf >= floor]
        if any(not doctypes.fields_match(spec, sure[0].value, c.value) for c in sure[1:]):
            problems[name] = "inconsistent"
        best = max(sure or cands, key=lambda c: c.conf)
        values[name], confs[name] = best.value, int(round(best.conf))
        if best.conf < floor and name not in problems:
            problems[name] = "low"
    return values, confs, problems
