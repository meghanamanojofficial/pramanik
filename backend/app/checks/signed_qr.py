"""What the QR code tells us, as signals."""
from .. import config
from ..services import qr_payload, signing
from ..services.signals import Severity, Signal


def check(qr: qr_payload.QRInfo, expect_qr: bool = False) -> list[Signal]:
    """`expect_qr` is set for photos: a QR that cannot be read there is more likely a capture problem than
    a missing code, so it is worth a note. A PDF that simply has no QR is left alone, as before."""
    if qr.kind == qr_payload.NONE:
        return [Signal("qr_none", Severity.WEAK, config.message("qr_none"))] if expect_qr else []
    if qr.kind == qr_payload.PLAIN:
        return [Signal("qr_plain", Severity.OK, config.message("qr_plain"))]
    if qr.kind == qr_payload.SIGNED:
        return [Signal("signed_qr_valid", Severity.OK, config.message("signed_qr_valid", kid=qr.kid))]
    # A signature that fails is an integrity concern; "no keys configured" is our setup, not the document's fault.
    severity = Severity.WEAK if qr.reason == signing.NO_KEYS else Severity.STRONG
    return [Signal("signed_qr_invalid_signature" if severity == Severity.STRONG else "signed_qr_unchecked",
                   severity, config.message(f"qr_sig_{qr.reason}"))]
