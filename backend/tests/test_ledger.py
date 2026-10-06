"""The reuse ledger: privacy, case-awareness, tamper evidence."""
import unittest

from support import DOC, FIELDS, Isolated  # noqa: F401

from app.checks import reuse
from app.services import ledger
from app.services.signals import Severity


class LedgerTests(Isolated):
    def record(self, case, fields=None, verdict="VERIFIED", stamp=None):
        return ledger.record(DOC, fields or FIELDS, case, "pdf", verdict, stamp)

    def test_off_without_a_key_and_never_guesses_one(self):
        import os
        del os.environ["PRAMANIK_FINGERPRINT_KEY"]
        self.assertFalse(ledger.enabled())
        self.assertIsNone(self.record("C1"))
        self.assertEqual(reuse.check(DOC, FIELDS, "C1", "pdf", None), [])

    def test_same_case_is_not_reuse_other_cases_are(self):
        fp, c1 = ledger.content_fingerprint(DOC, FIELDS), ledger.case_fingerprint("C1")
        self.record("C1")
        self.record("C1")  # the officer checked it twice in the same case
        self.assertEqual(ledger.other_case_count(fp, c1), 0)
        self.record("C2")
        self.assertEqual(ledger.other_case_count(fp, c1), 1)
        self.assertEqual(ledger.other_case_count(fp, ledger.case_fingerprint("C3")), 2)

    def test_different_content_is_a_different_certificate(self):
        self.assertNotEqual(ledger.content_fingerprint(DOC, FIELDS),
                            ledger.content_fingerprint(DOC, {**FIELDS, "income_amount": "250001"}))
        # formatting the schema normalises away does not change the fingerprint
        self.assertEqual(ledger.content_fingerprint(DOC, FIELDS),
                         ledger.content_fingerprint(DOC, {**FIELDS, "income_amount": "2,50,000"}))

    def test_signal_levels(self):
        for case in ("C1", "C2"):
            self.record(case)
        sig = reuse.check(DOC, FIELDS, "C9", "pdf", None)
        self.assertEqual([(s.name, s.severity) for s in sig], [("duplicate_scan_prior", Severity.WEAK)])
        for case in ("C3", "C4", "C5"):
            self.record(case)
        sig = reuse.check(DOC, FIELDS, "C9", "pdf", None)
        self.assertEqual([(s.name, s.severity) for s in sig], [("duplicate_scan_excessive", Severity.STRONG)])

    def test_nothing_readable_is_stored(self):
        self.record("CASE-SECRET-77")
        blob = (self.tmp / "ledger.db").read_bytes()
        for secret in (b"CASE-SECRET-77", b"INC-2024-0001", b"Asha", b"250000"):
            self.assertNotIn(secret, blob)

    def test_chain_detects_edits_and_deletions(self):
        for case in ("C1", "C2", "C3"):
            self.record(case)
        self.assertEqual(ledger.verify_chain(), (True, None))
        from sqlalchemy import text
        with ledger._get_engine().begin() as db:
            db.execute(text("UPDATE ledger SET verdict='MISMATCH' WHERE id=2"))
        self.assertEqual(ledger.verify_chain(), (False, 2))

    def test_chain_detects_a_deleted_row(self):
        for case in ("C1", "C2", "C3"):
            self.record(case)
        from sqlalchemy import text
        with ledger._get_engine().begin() as db:
            db.execute(text("DELETE FROM ledger WHERE id=2"))
        self.assertFalse(ledger.verify_chain()[0])

    def test_stamp_reuse_needs_a_real_stamp(self):
        import numpy as np
        blank = np.full((400, 400, 3), 255, np.uint8)
        dt = {**DOC, "stamp_region": [0.5, 0.5, 1.0, 1.0]}
        self.assertIsNone(reuse.stamp_hash(blank, dt))               # blank paper is not a stamp
        self.assertIsNone(reuse.stamp_hash(blank, DOC))              # no region configured
        stamped = blank.copy()
        stamped[250:380, 250:380] = 0
        h = reuse.stamp_hash(stamped, dt)
        self.assertIsNotNone(h)
        self.record("C1", stamp=h)
        other = {**FIELDS, "certificate_number": "INC-2024-0002"}    # a different certificate, same stamp
        found = reuse.check(DOC, other, "C2", "pdf", h)
        self.assertIn("stamp_reuse_detected", [s.name for s in found])
        self.assertEqual(reuse.check(DOC, FIELDS, "C2", "pdf", h)[0].name, "duplicate_scan_prior")  # same cert: not a stamp copy


if __name__ == "__main__":
    unittest.main()
