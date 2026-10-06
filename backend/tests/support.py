"""Shared test setup: import paths, an isolated signing-key store and ledger."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for sub in ("issuer_service", "backend"):
    sys.path.insert(0, str(ROOT / sub))

import signing as issuer_signing  # noqa: E402  (the issuer's signer)
from app.services import doctypes  # noqa: E402

DOC = doctypes.by_id("income_certificate")
FIELDS = {"certificate_number": "INC-2024-0001", "holder_name": "Asha Menon",
          "issue_date": "2026-01-01", "income_amount": "250000"}


class Isolated(unittest.TestCase):
    """Temp signing keys + temp ledger; nothing touches the real backend/config or backend/data."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.priv, self.pub = self.tmp / "priv", self.tmp / "issuer_keys.json"
        self.kid = issuer_signing.generate_key("revenue_dept", self.priv, self.pub)
        self._env = {k: os.environ.get(k) for k in ("ISSUER_KEYS_FILE", "PRAMANIK_FINGERPRINT_KEY", "DATABASE_URL")}
        os.environ["ISSUER_KEYS_FILE"] = str(self.pub)
        os.environ["PRAMANIK_FINGERPRINT_KEY"] = "ab" * 32
        os.environ["DATABASE_URL"] = "sqlite:///" + (self.tmp / "ledger.db").as_posix()

    def tearDown(self):
        for k, v in self._env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def token(self, fields=None, **kw):
        return issuer_signing.issue_token("revenue_dept", "income_certificate", fields or FIELDS,
                                          signing_dir=self.priv, public_keys=self.pub, **kw)
