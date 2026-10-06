"""Signed QR codes, the checks that read them, links, and the verdict refinement rules."""
import json
import unittest

from support import DOC, FIELDS, Isolated, issuer_signing  # noqa: F401  (sets import paths)

from app.checks import consistency, links, signed_qr
from app.services import qr_payload, signing, verdict as vr
from app.services.signals import Severity, Signal


def tamper_payload(token: str, **changes) -> str:
    """Edit the signed payload but keep the old signature (what a forger without the key can do)."""
    payload, sig = token.split(".")
    data = json.loads(signing.b64url_decode(payload))
    data["f"].update(changes)
    return signing.b64url_encode(json.dumps(data, sort_keys=True, separators=(",", ":")).encode()) + "." + sig


class SigningTests(Isolated):
    def test_valid_token(self):
        qr = qr_payload.interpret(self.token())
        self.assertEqual((qr.kind, qr.number, qr.kid), ("signed", FIELDS["certificate_number"], self.kid))
        self.assertEqual(qr.digital_signature, "valid")

    def test_plain_number_and_empty(self):
        self.assertEqual(qr_payload.interpret("INC-2024-0001").kind, "plain")
        self.assertEqual(qr_payload.interpret(None).kind, "none")

    def test_edited_payload_fails_and_is_not_trusted(self):
        qr = qr_payload.interpret(tamper_payload(self.token(), income_amount="999999"))
        self.assertEqual((qr.kind, qr.reason, qr.number), ("signed_invalid", signing.BAD_SIGNATURE, None))

    def test_unknown_key_and_malformed(self):
        token = self.token()
        self.pub.write_text(json.dumps({"keys": []}))
        self.assertEqual(qr_payload.interpret(token).reason, signing.NO_KEYS)
        self.assertEqual(signing.verify_token("not.atoken")[2], signing.MALFORMED)

    def test_revoked_key_rejected_but_retired_key_still_verifies(self):
        old = self.token()
        new_kid = issuer_signing.generate_key("revenue_dept", self.priv, self.pub)  # old becomes "retired"
        self.assertEqual(qr_payload.interpret(old).kind, "signed")
        keys = json.loads(self.pub.read_text())
        keys["keys"][0]["status"] = "revoked"
        self.pub.write_text(json.dumps(keys))
        self.assertEqual(qr_payload.interpret(old).reason, signing.KEY_REVOKED)
        self.assertEqual(qr_payload.interpret(self.token(kid=new_kid)).kind, "signed")

    def test_issuer_cannot_sign_for_a_document_type_that_is_not_its_own(self):
        t = issuer_signing.issue_token("revenue_dept", "income_certificate", FIELDS, signing_dir=self.priv, public_keys=self.pub)
        data = json.loads(signing.b64url_decode(t.split(".")[0]))
        self.assertEqual(data["iss"], DOC["issuer_id"])  # sanity: the happy path uses the right issuer
        other = issuer_signing.generate_key("other_dept", self.priv, self.pub)
        forged = issuer_signing.issue_token("other_dept", "income_certificate", FIELDS, kid=other,
                                            signing_dir=self.priv, public_keys=self.pub)
        self.assertEqual(qr_payload.interpret(forged).kind, "signed_invalid")

    def test_signal_severities(self):
        self.assertEqual(signed_qr.check(qr_payload.interpret(self.token()))[0].severity, Severity.OK)
        bad = signed_qr.check(qr_payload.interpret(tamper_payload(self.token(), income_amount="1")))[0]
        self.assertEqual((bad.name, bad.severity), ("signed_qr_invalid_signature", Severity.STRONG))
        self.assertEqual(signed_qr.check(qr_payload.interpret(None)), [])  # a PDF with no QR is left alone
        self.assertEqual(signed_qr.check(qr_payload.interpret(None), expect_qr=True)[0].severity, Severity.WEAK)
        token = self.token()
        self.pub.write_text(json.dumps({"keys": []}))  # our setup problem, not the document's
        self.assertEqual(signed_qr.check(qr_payload.interpret(token))[0].severity, Severity.WEAK)

    def test_consistency_flags_only_differing_fields_and_never_repeats_values(self):
        qr = qr_payload.interpret(self.token())
        self.assertEqual(consistency.check(DOC, FIELDS, qr), [])
        printed = {**FIELDS, "income_amount": "350000", "holder_name": "Menon  ASHA"}  # name differs only by order/case
        found = consistency.check(DOC, printed, qr)
        self.assertEqual([s.region for s in found], ["income_amount"])
        self.assertTrue(all(s.severity == Severity.FAIL for s in found))
        self.assertNotIn("350000", found[0].detail)
        self.assertEqual(consistency.check(DOC, {**FIELDS, "holder_name": "Asha Menan"}, qr)[0].region, "holder_name")


class LinkTests(unittest.TestCase):
    def names(self, text):
        return sorted(s.name for s in links.check(text))

    def test_official_link_is_clean(self):
        self.assertEqual(self.names("See https://edistrict.kerala.gov.in/verify/INC-1."), [])

    def test_insecure_shortener_lookalike_unknown(self):
        self.assertEqual(self.names("http://bit.ly/x"), ["insecure_http_link", "malicious_link_domain"])
        self.assertEqual(self.names("https://edistrict.kerala.gov.in.evil.example/x"), ["malicious_link_domain"])
        self.assertEqual(self.names("https://kerala-gov-in.example/x"), ["malicious_link_domain"])
        self.assertEqual(self.names("https://edistrict.kerala.gov.in@evil.example/x"), ["unknown_link_domain"])
        self.assertEqual(self.names("www.example.org"), ["unknown_link_domain"])


def S(name, sev, detail="d"):
    return Signal(name, sev, detail)


class FinalizeTests(unittest.TestCase):
    """The only way a decision changes: VERIFIED may become worse or carry a caveat, never better."""

    def decision(self, verdict, reasons=("r",)):
        return {"verdict": verdict, "reasons": list(reasons), "route": "direct_issuer", "issuer_result": None, "issuer_note": ""}

    def verdict(self, base, signals, scanned=False):
        return vr.finalize(self.decision(base), signals, scanned)["verdict"]

    def test_table(self):
        ok, weak, strong, fail = Severity.OK, Severity.WEAK, Severity.STRONG, Severity.FAIL
        cases = [
            ("clean", "VERIFIED", [S("a", ok)], "VERIFIED"),
            ("weak", "VERIFIED", [S("a", weak)], "VERIFIED_WITH_WARNINGS"),
            ("strong", "VERIFIED", [S("a", strong)], "MATCHES_RECORD_INTEGRITY_CONCERNS"),
            ("strong beats weak", "VERIFIED", [S("a", weak), S("b", strong)], "MATCHES_RECORD_INTEGRITY_CONCERNS"),
            ("contradicts signed QR", "VERIFIED", [S("a", strong), S("b", fail)], "MISMATCH"),
            ("mismatch stays", "MISMATCH", [S("a", ok)], "MISMATCH"),
            ("suspicious stays", "SUSPICIOUS", [S("a", ok)], "SUSPICIOUS"),
            ("unverifiable stays", "UNVERIFIABLE", [S("a", weak)], "UNVERIFIABLE"),
            ("signals never rescue a mismatch", "MISMATCH", [], "MISMATCH"),
        ]
        for name, base, signals, expected in cases:
            with self.subTest(name):
                self.assertEqual(self.verdict(base, signals), expected)

    def test_warning_reasons_list_the_details(self):
        out = vr.finalize(self.decision("VERIFIED"), [S("a", Severity.WEAK, "look at this")])
        self.assertIn("look at this", out["reasons"])

    def test_scan_caveat_only_on_accusations_from_images(self):
        self.assertEqual(len(vr.finalize(self.decision("MISMATCH"), [], scanned=True)["reasons"]), 2)
        self.assertEqual(len(vr.finalize(self.decision("MISMATCH"), [], scanned=False)["reasons"]), 1)
        self.assertEqual(len(vr.finalize(self.decision("VERIFIED"), [], scanned=True)["reasons"]), 1)


if __name__ == "__main__":
    unittest.main()
