"""Run:  python -m unittest discover -s issuer_service/tests -v

Serves the real IssuerCore over real HTTP (stdlib server standing in for the
FastAPI adapter) and calls it with the real backend client.
"""
import json
import os
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "issuer_service"))
sys.path.insert(0, str(ROOT / "backend"))

import setup_keys  # noqa: E402
from core import IssuerCore  # noqa: E402
from app import issuer_client  # noqa: E402

RECORDS = [
    {"certificate_number": "INC-2024-0001", "status": "active", "income": 250000},
    {"certificate_number": "INC-2024-0002", "status": "revoked", "income": 90000},
]


def make_handler(core):
    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            cert = self.path.rsplit("/", 1)[-1]
            status, body = core.lookup(self.headers.get("X-API-Key"), cert)
            data = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *a):
            pass
    return H


class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.records = self.tmp / "records.json"
        self.records.write_text(json.dumps(RECORDS))
        (self.tmp / "registries.json").write_text(json.dumps({"registries": [
            {"issuer_id": "revenue_dept", "prefix": "INC-", "file": "records.json"},
            {"issuer_id": "land_dept", "prefix": "LND-", "file": "records.json"},
        ]}))
        self.keys = self.tmp / "keys.json"
        self.env = self.tmp / ".env"
        self.audit = self.tmp / "audit.jsonl"
        self.core = IssuerCore(self.tmp / "registries.json", self.keys, self.audit, rate_limit_per_minute=5)

        self.server = HTTPServer(("127.0.0.1", 0), make_handler(self.core))
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        port = self.server.server_port

        self.cfg = self.tmp / "issuers.json"
        self.cfg.write_text(json.dumps({"issuers": [{
            "issuer_id": "revenue_dept", "prefixes": ["INC-"],
            "base_url": f"http://127.0.0.1:{port}",
            "api_key_env": "ISSUER_KEY_REVENUE_DEPT", "timeout_seconds": 2}]}))
        os.environ["ISSUERS_CONFIG"] = str(self.cfg)
        os.environ.pop("ISSUER_KEY_REVENUE_DEPT", None)
        issuer_client._env_loaded = True  # don't read the real backend/.env

        setup_keys.main(self.cfg, self.env, self.keys)
        os.environ["ISSUER_KEY_REVENUE_DEPT"] = setup_keys.read_env(self.env)["ISSUER_KEY_REVENUE_DEPT"]

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        os.environ.pop("ISSUERS_CONFIG", None)
        os.environ.pop("ISSUER_KEY_REVENUE_DEPT", None)

    def test_found(self):
        r = issuer_client.lookup("INC-2024-0001")
        self.assertEqual(r.outcome, "found")
        self.assertEqual(r.record, RECORDS[0])

    def test_revoked_record_is_returned_with_status(self):
        r = issuer_client.lookup("INC-2024-0002")
        self.assertEqual((r.outcome, r.record["status"]), ("found", "revoked"))

    def test_unknown_number_not_found(self):
        self.assertEqual(issuer_client.lookup("INC-9999-9999").outcome, "not_found")

    def test_unconnected_issuer_makes_no_call(self):
        self.server.shutdown()  # prove no HTTP is attempted
        self.assertEqual(issuer_client.lookup("XYZ-1").outcome, "unconnected")

    def test_wrong_key_is_unavailable_not_forged(self):
        os.environ["ISSUER_KEY_REVENUE_DEPT"] = "pk_wrong"
        r = issuer_client.lookup("INC-2024-0001")
        self.assertEqual(r.outcome, "unavailable")
        self.assertIn("401", r.detail)

    def test_missing_key(self):
        del os.environ["ISSUER_KEY_REVENUE_DEPT"]
        self.assertEqual(issuer_client.lookup("INC-2024-0001").outcome, "unavailable")

    def test_key_scoped_to_one_issuer(self):
        # LND- numbers belong to land_dept; revenue key must be refused
        status, _ = self.core.lookup(os.environ["ISSUER_KEY_REVENUE_DEPT"], "LND-1")
        self.assertEqual(status, 403)

    def test_issuer_down(self):
        self.server.shutdown()
        self.server.server_close()
        self.assertEqual(issuer_client.lookup("INC-2024-0001").outcome, "unavailable")

    def test_rate_limit(self):
        codes = [self.core.lookup(os.environ["ISSUER_KEY_REVENUE_DEPT"], "INC-2024-0001")[0] for _ in range(7)]
        self.assertEqual(codes, [200] * 5 + [429] * 2)

    def test_revoked_api_key_rejected(self):
        data = json.loads(self.keys.read_text())
        data["keys"][0]["revoked"] = True
        self.keys.write_text(json.dumps(data))
        self.assertEqual(issuer_client.lookup("INC-2024-0001").outcome, "unavailable")

    def test_rotate_invalidates_old_key(self):
        old = os.environ["ISSUER_KEY_REVENUE_DEPT"]
        setup_keys.main(self.cfg, self.env, self.keys, rotate=True)
        self.assertEqual(self.core.lookup(old, "INC-2024-0001")[0], 401)
        new = setup_keys.read_env(self.env)["ISSUER_KEY_REVENUE_DEPT"]
        self.assertEqual(self.core.lookup(new, "INC-2024-0001")[0], 200)

    def test_editing_json_takes_effect_without_restart(self):
        self.assertEqual(issuer_client.lookup("INC-2024-0003").outcome, "not_found")
        import time; time.sleep(0.05)
        self.records.write_text(json.dumps(RECORDS + [{"certificate_number": "INC-2024-0003", "status": "active"}]))
        os.utime(self.records, (time.time() + 5, time.time() + 5))
        self.assertEqual(issuer_client.lookup("INC-2024-0003").outcome, "found")

    def test_keys_file_stores_only_hashes(self):
        raw = os.environ["ISSUER_KEY_REVENUE_DEPT"]
        self.assertNotIn(raw, self.keys.read_text())

    def test_audit_log_has_no_certificate_data(self):
        issuer_client.lookup("INC-2024-0001")
        log = self.audit.read_text()
        self.assertIn('"outcome": "found"', log)
        self.assertNotIn("INC-2024", log)
        self.assertNotIn("250000", log)


if __name__ == "__main__":
    unittest.main()
