"""Printed text versus the issuer-signed QR on the same document."""
from typing import Optional

from .. import config
from ..services import doctypes, qr_payload
from ..services.signals import Severity, Signal


def check(doc_type: Optional[dict], printed: dict, qr: qr_payload.QRInfo) -> list[Signal]:
    """Only a QR with a valid signature is evidence. Each differing field is a FAIL (the document
    contradicts what its issuer signed). Values are not repeated in the message."""
    if doc_type is None or qr.kind != qr_payload.SIGNED:
        return []
    if qr.doc_type_id != doc_type["id"]:
        return [Signal("signed_qr_type_mismatch", Severity.STRONG, config.message("signed_type_mismatch"))]
    signals = []
    for spec in doc_type["fields"]:
        name = spec["name"]
        if name == doc_type["key_field"] or name not in qr.fields or not printed.get(name):
            continue  # the number is already compared by the verdict rules
        if not doctypes.fields_match(spec, printed[name], qr.fields[name]):
            signals.append(Signal("signed_qr_field_mismatch", Severity.FAIL,
                                  config.message("signed_field_mismatch", field=name), region=name))
    return signals
