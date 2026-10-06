"""What a QR code on a certificate means: a plain certificate number, or an issuer-signed token.

interpret() never raises. The `number` it returns is what the verdict rules compare with the printed
certificate number: the plain text for a plain QR, the signed key field for a valid token, and None for
a token whose signature does not hold (an unsigned claim must not be trusted).
"""
import re
from dataclasses import dataclass, field
from typing import Optional

from . import doctypes, signing

NONE, PLAIN, SIGNED, SIGNED_INVALID = "none", "plain", "signed", "signed_invalid"
_TOKEN = re.compile(r"^[A-Za-z0-9_-]{16,}\.[A-Za-z0-9_-]{16,}$")


@dataclass
class QRInfo:
    kind: str = NONE
    raw: Optional[str] = None
    number: Optional[str] = None                 # see module docstring
    fields: dict = field(default_factory=dict)   # signed field values, only when kind == SIGNED
    doc_type_id: Optional[str] = None
    kid: Optional[str] = None
    reason: str = ""                             # signing.* code when kind == SIGNED_INVALID

    @property
    def digital_signature(self) -> str:
        return {SIGNED: "valid", SIGNED_INVALID: "invalid"}.get(self.kind, "not_applicable")


def interpret(raw: Optional[str]) -> QRInfo:
    raw = (raw or "").strip()
    if not raw:
        return QRInfo()
    if not _TOKEN.match(raw):
        return QRInfo(PLAIN, raw, number=raw)

    ok, payload, reason = signing.verify_token(raw)
    if not ok:
        return QRInfo(SIGNED_INVALID, raw, reason=reason)
    doc_type = doctypes.by_id(str(payload.get("t", "")))
    if doc_type is None:
        return QRInfo(SIGNED_INVALID, raw, reason=signing.MALFORMED)
    if payload["iss"] != doc_type.get("issuer_id"):  # an issuer may only sign for its own document types
        return QRInfo(SIGNED_INVALID, raw, reason=signing.UNKNOWN_KEY)
    return QRInfo(SIGNED, raw, number=str(payload["f"].get(doc_type["key_field"]) or "") or None,
                  fields={k: str(v) for k, v in payload["f"].items()}, doc_type_id=doc_type["id"],
                  kid=payload.get("kid"))
