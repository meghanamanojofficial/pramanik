"""The risk score and the issuer-answer cache."""
import json
import os
import unittest

from support import DOC, FIELDS, Isolated  # noqa: F401

from app import config
from app.services import issuer_cache, ledger, risk
from app.services.signals import Severity, Signal


def S(name, sev, detail="detail"):
    return Signal(name, sev, detail)


def assess(verdict, signals=(), input_type="pdf", conf=None, sig="not_applicable"):
    return risk.assess(verdict, list(signals), input_type, conf or {}, sig)


class RiskTests(unittest.TestCase):
    def test_clean_signed_pdf_is_zero_and_low(self):
        r = assess("VERIFIED", sig="valid")
        self.assertEqual((r["score"], r["level"]), (0, "low"))

    def test_nothing_judged_means_no_score(self):
        for verdict in ("RESCAN", "INCONCLUSIVE", "UNVERIFIABLE"):
            r = assess(verdict, [S("quality_blur", Severity.FAIL)])
            self.assertEqual((r["score"], r["level"], r["factors"]), (None, "not_assessed", []), verdict)

    def test_ordering_of_verdicts(self):
        scores = [assess(v)["score"] for v in ("VERIFIED", "VERIFIED_WITH_WARNINGS", "MATCHES_RECORD_INTEGRITY_CONCERNS",
                                                "MISMATCH", "SUSPICIOUS")]
        self.assertEqual(scores, sorted(scores))
        self.assertEqual(len(set(scores)), 5)

    def test_levels(self):
        self.assertEqual(assess("VERIFIED_WITH_WARNINGS")["level"], "low")
        self.assertEqual(assess("MATCHES_RECORD_INTEGRITY_CONCERNS", [S("duplicate_scan_prior", Severity.WEAK)])["level"], "medium")
        self.assertEqual(assess("MISMATCH")["level"], "high")

    def test_every_point_is_explained_and_the_sum_matches(self):
        r = assess("MATCHES_RECORD_INTEGRITY_CONCERNS",
                   [S("signed_qr_invalid_signature", Severity.STRONG, "forged"), S("qr_plain", Severity.OK)],
                   input_type="scan", conf={"income_amount": 70})
        self.assertEqual(r["score"], sum(f["points"] for f in r["factors"]))
        self.assertIn("forged", [f["detail"] for f in r["factors"]])
        self.assertNotIn("qr_plain", [f["name"] for f in r["factors"]])  # informational signals add nothing
        self.assertEqual({f["name"] for f in r["factors"]}, {"verdict", "signed_qr_invalid_signature", "read_by_ocr", "low_ocr_confidence"})
        self.assertEqual([f["points"] for f in r["factors"]], sorted((f["points"] for f in r["factors"]), key=abs, reverse=True))

    def test_valid_signature_lowers_risk_only_for_matching_documents(self):
        self.assertEqual(assess("VERIFIED_WITH_WARNINGS", sig="valid")["score"], 0)
        self.assertEqual(assess("MISMATCH", sig="valid")["score"], 80)  # a signature never excuses a mismatch

    def test_clamped(self):
        many = [S("signed_qr_field_mismatch", Severity.FAIL)] * 5
        self.assertEqual(assess("SUSPICIOUS", many)["score"], 100)

    def test_unlisted_signal_falls_back_to_its_severity(self):
        self.assertEqual(assess("VERIFIED", [S("something_new", Severity.WEAK)])["score"], config.risk()["severity_points"]["weak"])


def live_answer(found=True, status="active", matches=None, values=None, reachable=True):
    return {"reachable": reachable, "found": found, "status": status if found else "",
            "matches": matches if matches is not None else {k: True for k in FIELDS},
            "values": values or {}, "error": "", "detail": ""}


class Counter:
    """A stand-in for the live issuer that counts how often it is asked."""
    def __init__(self, **answer):
        self.answer, self.calls = answer, 0

    def __call__(self, document_type, fields):
        self.calls += 1
        return live_answer(**self.answer)


class CacheTests(Isolated):
    def ask(self, issuer, fields=None, fresh=False):
        return issuer_cache.verify(issuer, DOC["id"], fields or FIELDS, fresh)

    def test_second_check_is_answered_from_the_cache(self):
        issuer = Counter()
        first, second = self.ask(issuer), self.ask(issuer)
        self.assertEqual((first["source"], second["source"], issuer.calls), ("live", "cache", 1))
        self.assertEqual((second["found"], second["status"], second["matches"]), (True, "active", first["matches"]))

    def test_an_edited_value_is_never_answered_from_a_genuine_entry(self):
        issuer = Counter()
        self.ask(issuer)
        edited = self.ask(issuer, {**FIELDS, "income_amount": "350000"})
        self.assertEqual((edited["source"], issuer.calls), ("live", 2))

    def test_fresh_skips_the_cache_and_refreshes_it(self):
        issuer = Counter()
        self.ask(issuer)
        self.assertEqual(self.ask(issuer, fresh=True)["source"], "live")
        self.assertEqual(issuer.calls, 2)
        self.assertEqual(self.ask(issuer)["source"], "cache")

    def test_entries_expire(self):
        issuer = Counter()
        self.ask(issuer)
        fp = ledger.content_fingerprint(DOC, FIELDS)
        self.assertIsNotNone(ledger.cache_get(fp))
        import time
        self.assertIsNone(ledger.cache_get(fp, now=int(time.time()) + config.cache()["ttl_seconds"] + 1))

    def test_only_clear_found_answers_are_stored(self):
        for answer in (dict(found=False), dict(reachable=False, found=False), dict(values={"income_amount": "250000"})):
            with self.subTest(answer):
                self.tearDown(); self.setUp()
                issuer = Counter(**answer)
                self.ask(issuer); self.ask(issuer)
                self.assertEqual(issuer.calls, 2)

    def test_a_record_that_disappears_clears_the_old_answer(self):
        self.ask(Counter())
        self.ask(Counter(found=False), fresh=True)
        self.assertEqual(self.ask(Counter(found=False))["source"], "live")

    def test_a_tampered_database_row_is_not_believed(self):
        """Someone with write access to the file tries to make a bad document 'verified'."""
        issuer = Counter(matches={k: False for k in FIELDS})
        self.ask(issuer)
        from sqlalchemy import text
        flipped = json.dumps({k: True for k in FIELDS}, sort_keys=True)
        with ledger._get_engine().begin() as db:
            db.execute(text("UPDATE issuer_cache SET matches=:m"), {"m": flipped})
        again = self.ask(issuer)
        self.assertEqual((again["source"], again["matches"][next(iter(FIELDS))]), ("live", False))

    def test_a_status_edit_is_also_detected(self):
        self.ask(Counter(status="revoked"))
        from sqlalchemy import text
        with ledger._get_engine().begin() as db:
            db.execute(text("UPDATE issuer_cache SET status='active'"))
        self.assertEqual(self.ask(Counter(status="revoked"))["source"], "live")

    def test_off_without_the_key_or_when_disabled(self):
        del os.environ["PRAMANIK_FINGERPRINT_KEY"]
        issuer = Counter()
        self.ask(issuer); self.ask(issuer)
        self.assertEqual(issuer.calls, 2)
        os.environ["PRAMANIK_FINGERPRINT_KEY"] = "ab" * 32
        off = self.tmp / "cache.json"
        off.write_text(json.dumps({"enabled": False, "ttl_seconds": 600}))
        os.environ["CACHE_CONFIG"] = str(off)
        try:
            issuer = Counter()
            self.ask(issuer); self.ask(issuer)
            self.assertEqual(issuer.calls, 2)
        finally:
            del os.environ["CACHE_CONFIG"]

    def test_the_cache_stores_no_readable_content(self):
        self.ask(Counter())
        blob = (self.tmp / "ledger.db").read_bytes()
        for secret in (b"INC-2024-0001", b"Asha", b"250000"):
            self.assertNotIn(secret, blob)


if __name__ == "__main__":
    unittest.main()
