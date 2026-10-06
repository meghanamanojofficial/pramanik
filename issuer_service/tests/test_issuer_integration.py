"""Run from the repo root:  python -m unittest discover -s issuer_service/tests -v

Serves the real IssuerCore over real HTTP (a stdlib server standing in for the FastAPI adapter)
and drives it with the real backend client, schema loader, extractor, verdict rules and row builder.
"""
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "issuer_service"))
sys.path.insert(0, str(ROOT / "backend"))

import setup_keys  # noqa: E402
from core import IssuerCore  # noqa: E402
from app import issuer_client  # noqa: E402
from app.issuers import mock_issuer  # noqa: E402
from app import config  # noqa: E402
from app.services import compare, doctypes, extract, verdict as vr  # noqa: E402

SCHEMA = ROOT / "backend" / "config" / "document_types.json"
DOC = next(t for t in json.loads(SCHEMA.read_text())["document_types"] if t["id"] == "income_certificate")

ACTIVE = {"certificate_number": "INC-2024-0001", "holder_name": "Asha Menon",
          "issue_date": "2026-01-01", "income_amount": "250000", "status": "active"}
REVOKED = {"certificate_number": "INC-2024-0002", "holder_name": "Ravi Nair",
           "issue_date": "2025-06-30", "income_amount": "90000", "status": "revoked"}


def make_handler(core):
    class H(BaseHTTPRequestHandler):
        def _send(self, status, body):
            data = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_POST(self):
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            self._send(*core.verify(self.headers.get("X-API-Key"), payload.get("document_type"), payload.get("fields")))

        def do_GET(self):
            self._send(*core.stats(self.headers.get("X-API-Key")))

        def log_message(self, *a):
            pass
    return H


def printed_text(values: dict, drop: str = "") -> str:
    """What PyMuPDF would read from a generated PDF: header lines, then '<label>: <value>' lines."""
    lines = list(DOC["header_lines"])
    lines += [f"{f['label']}: {values[f['name']]}" for f in DOC["fields"] if f["name"] != drop]
    return "\n".join(lines)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.records = self.tmp / "records.json"
        self.records.write_text(json.dumps([ACTIVE, REVOKED]))
        self.reg_path = self.tmp / "registries.json"
        self.write_registries(issuer_id="revenue_dept", disclose=False)
        self.keys, self.env, self.audit = self.tmp / "keys.json", self.tmp / ".env", self.tmp / "audit.jsonl"
        self.core = IssuerCore(self.reg_path, self.keys, self.audit, rate_limit_per_minute=5)

        self.server = HTTPServer(("127.0.0.1", 0), make_handler(self.core))
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.cfg = self.tmp / "issuers.json"
        self.cfg.write_text(json.dumps({"issuers": [{
            "issuer_id": "revenue_dept", "document_types": ["income_certificate"],
            "base_url": f"http://127.0.0.1:{self.server.server_port}",
            "api_key_env": "ISSUER_KEY_REVENUE_DEPT", "timeout_seconds": 2}]}))
        os.environ["ISSUERS_CONFIG"] = str(self.cfg)
        os.environ.pop("ISSUER_KEY_REVENUE_DEPT", None)
        issuer_client._env_loaded = True  # don't read the real backend/.env

        setup_keys.main(self.cfg, self.env, self.keys)
        os.environ["ISSUER_KEY_REVENUE_DEPT"] = setup_keys.read_env(self.env)["ISSUER_KEY_REVENUE_DEPT"]
        self.key = os.environ["ISSUER_KEY_REVENUE_DEPT"]

    def write_registries(self, issuer_id, disclose):
        self.reg_path.write_text(json.dumps({"schema_file": str(SCHEMA), "registries": [{
            "issuer_id": issuer_id, "document_type": "income_certificate",
            "file": "records.json", "disclose_values": disclose}]}))

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        os.environ.pop("ISSUERS_CONFIG", None)
        os.environ.pop("ISSUER_KEY_REVENUE_DEPT", None)

    def fields(self, **override):
        base = {k: ACTIVE[k] for k in ("certificate_number", "holder_name", "issue_date", "income_amount")}
        return {**base, **override}


class IssuerTests(Base):
    def test_all_fields_match(self):
        r = issuer_client.verify("income_certificate", self.fields())
        self.assertEqual((r.outcome, r.status), ("found", "active"))
        self.assertEqual(set(r.matches), {f["name"] for f in DOC["fields"]})
        self.assertTrue(all(r.matches.values()))

    def test_issuer_never_returns_its_record(self):
        status, body = self.core.verify(self.key, "income_certificate", self.fields())
        self.assertEqual(status, 200)
        self.assertEqual(set(body), {"issuer_id", "found", "status", "matches"})
        self.assertNotIn("250000", json.dumps(body))
        self.assertNotIn("Asha", json.dumps(body))

    def test_edited_field_flagged_only_that_field(self):
        r = issuer_client.verify("income_certificate", self.fields(income_amount="350000"))
        self.assertFalse(r.matches["income_amount"])
        self.assertTrue(all(v for k, v in r.matches.items() if k != "income_amount"))

    def test_name_ignores_case_spacing_punctuation_and_order(self):
        for variant in ("ASHA   MENON", "asha menon", "Menon, Asha", "Asha  Menon."):
            r = issuer_client.verify("income_certificate", self.fields(holder_name=variant))
            self.assertTrue(r.matches["holder_name"], variant)

    def test_name_one_letter_differences_are_rejected(self):
        """Regression: the old fuzzy rule (threshold 90) accepted these."""
        for variant in ("Asha Menan", "Asha Menons", "Ashaa Menon", "Rahul Verma", "Asha"):
            r = issuer_client.verify("income_certificate", self.fields(holder_name=variant))
            self.assertFalse(r.matches["holder_name"], variant)

    def test_unknown_compare_method_is_a_503_not_a_wrong_answer(self):
        types = json.loads(SCHEMA.read_text())
        for f in types["document_types"][0]["fields"]:
            if f["name"] == "holder_name":
                f["compare"] = {"method": "sounds_like"}
        bad = self.tmp / "bad_types.json"
        bad.write_text(json.dumps(types))
        cfg = json.loads(self.reg_path.read_text())
        cfg["schema_file"] = str(bad)
        self.reg_path.write_text(json.dumps(cfg))
        self.assertEqual(self.core.verify(self.key, "income_certificate", self.fields())[0], 503)

    def test_normalize_rule_comes_from_schema(self):
        r = issuer_client.verify("income_certificate", self.fields(income_amount="2,50,000"))
        self.assertTrue(r.matches["income_amount"])

    def test_revoked_status_returned(self):
        f = {k: REVOKED[k] for k in ("certificate_number", "holder_name", "issue_date", "income_amount")}
        r = issuer_client.verify("income_certificate", f)
        self.assertEqual((r.outcome, r.status), ("found", "revoked"))

    def test_unknown_number_not_found(self):
        self.assertEqual(issuer_client.verify("income_certificate",
                         self.fields(certificate_number="INC-9999-9999")).outcome, "not_found")

    def test_unconnected_document_type_makes_no_call(self):
        self.server.shutdown()
        self.assertEqual(issuer_client.verify("land_record", {}).outcome, "unconnected")

    def test_wrong_key_is_unavailable_not_forged(self):
        os.environ["ISSUER_KEY_REVENUE_DEPT"] = "pk_wrong"
        r = issuer_client.verify("income_certificate", self.fields())
        self.assertEqual((r.outcome, r.error), ("unavailable", "key_rejected"))
        self.assertIn("401", r.detail)

    def test_missing_key(self):
        del os.environ["ISSUER_KEY_REVENUE_DEPT"]
        r = issuer_client.verify("income_certificate", self.fields())
        self.assertEqual((r.outcome, r.error), ("unavailable", "not_configured"))

    def test_key_scoped_to_one_issuer(self):
        self.write_registries(issuer_id="some_other_dept", disclose=False)
        self.assertEqual(self.core.verify(self.key, "income_certificate", self.fields())[0], 403)

    def test_issuer_down(self):
        self.server.shutdown()
        self.server.server_close()
        r = issuer_client.verify("income_certificate", self.fields())
        self.assertEqual((r.outcome, r.error), ("unavailable", "unreachable"))

    def test_records_file_missing_is_503_not_a_crash(self):
        self.records.unlink()
        self.assertEqual(self.core.verify(self.key, "income_certificate", self.fields())[0], 503)
        r = issuer_client.verify("income_certificate", self.fields())
        self.assertEqual((r.outcome, r.error), ("unavailable", "registry_unavailable"))

    def test_rate_limited_is_reported_as_such(self):
        for _ in range(5):
            issuer_client.verify("income_certificate", self.fields())
        r = issuer_client.verify("income_certificate", self.fields())
        self.assertEqual((r.outcome, r.error), ("unavailable", "rate_limited"))

    def test_plain_http_to_a_remote_issuer_is_refused_before_the_key_is_sent(self):
        cfg = json.loads(self.cfg.read_text())
        cfg["issuers"][0]["base_url"] = "http://issuer.example.gov.in"
        self.cfg.write_text(json.dumps(cfg))
        r = issuer_client.verify("income_certificate", self.fields())
        self.assertEqual((r.outcome, r.error), ("unavailable", "insecure_transport"))
        os.environ["PRAMANIK_ALLOW_INSECURE_HTTP"] = "1"
        try:  # allowed explicitly: it now tries (and fails to resolve) instead of refusing
            self.assertNotEqual(issuer_client.verify("income_certificate", self.fields()).error, "insecure_transport")
        finally:
            del os.environ["PRAMANIK_ALLOW_INSECURE_HTTP"]

    def test_rate_limit(self):
        codes = [self.core.verify(self.key, "income_certificate", self.fields())[0] for _ in range(7)]
        self.assertEqual(codes, [200] * 5 + [429] * 2)

    def test_revoked_api_key_rejected(self):
        data = json.loads(self.keys.read_text())
        data["keys"][0]["revoked"] = True
        self.keys.write_text(json.dumps(data))
        self.assertEqual(issuer_client.verify("income_certificate", self.fields()).error, "key_rejected")

    def test_rotate_invalidates_old_key(self):
        setup_keys.main(self.cfg, self.env, self.keys, rotate=True)
        self.assertEqual(self.core.verify(self.key, "income_certificate", self.fields())[0], 401)
        new = setup_keys.read_env(self.env)["ISSUER_KEY_REVENUE_DEPT"]
        self.assertEqual(self.core.verify(new, "income_certificate", self.fields())[0], 200)

    def test_editing_records_takes_effect_without_restart(self):
        f = self.fields(certificate_number="INC-2024-0003")
        self.assertEqual(issuer_client.verify("income_certificate", f).outcome, "not_found")
        self.records.write_text(json.dumps([ACTIVE, REVOKED, {**ACTIVE, "certificate_number": "INC-2024-0003"}]))
        os.utime(self.records, (time.time() + 5, time.time() + 5))
        self.assertEqual(issuer_client.verify("income_certificate", f).outcome, "found")

    def test_disclosure_is_opt_in_per_registry(self):
        self.write_registries(issuer_id="revenue_dept", disclose=True)
        r = issuer_client.verify("income_certificate", self.fields(income_amount="350000"))
        self.assertEqual(r.values["income_amount"], "250000")

    def test_stats_counts_records(self):
        self.assertEqual(issuer_client.count_records(), 2)
        self.assertEqual(mock_issuer.count_records(), 2)

    def test_keys_file_stores_only_hashes(self):
        self.assertNotIn(self.key, self.keys.read_text())

    def test_audit_log_has_no_certificate_data(self):
        issuer_client.verify("income_certificate", self.fields())
        log = self.audit.read_text()
        self.assertIn('"outcome": "found"', log)
        for secret in ("INC-2024", "250000", "Asha"):
            self.assertNotIn(secret, log)


class PipelineTests(Base):
    """Document text -> detect type -> extract fields -> issuer -> verdict -> rows."""

    def run_text(self, text, qr=None):
        doc_type = doctypes.detect(text)
        fields = extract.extract_fields(text, doc_type) if doc_type else {}
        decision = vr.decide(doc_type, fields, qr, mock_issuer.verify)
        rows = compare.field_rows(doc_type, fields, decision["issuer_result"], decision["issuer_note"])
        return decision, rows

    def test_genuine_is_verified(self):
        d, rows = self.run_text(printed_text(ACTIVE))
        self.assertEqual(d["verdict"], "VERIFIED")
        self.assertEqual(compare.coverage(rows), "4 of 4 printed fields confirmed with issuer")

    def test_edited_amount_is_a_mismatch_and_issuer_value_not_shown(self):
        d, rows = self.run_text(printed_text({**ACTIVE, "income_amount": "350000"}))
        self.assertEqual(d["verdict"], "MISMATCH")
        self.assertEqual(d["reasons"], ["income_amount on the document does not match the issuer record."])
        row = next(r for r in rows if r["field"] == "income_amount")
        self.assertEqual((row["document"], row["issuer"], row["match"]), ("350000", compare.MISMATCH, False))
        self.assertEqual(compare.coverage(rows), "3 of 4 printed fields confirmed with issuer")

    def test_unknown_number_suspicious(self):
        d, _ = self.run_text(printed_text({**ACTIVE, "certificate_number": "INC-9999-9999"}))
        self.assertEqual((d["verdict"], d["reasons"]), ("SUSPICIOUS", ["Issuer has no record of this certificate number."]))

    def test_revoked_suspicious(self):
        d, _ = self.run_text(printed_text(REVOKED))
        self.assertEqual((d["verdict"], d["reasons"]), ("SUSPICIOUS", ["Issuer lists this certificate as revoked."]))

    def test_unreadable_field_unverifiable(self):
        d, _ = self.run_text(printed_text(ACTIVE, drop="income_amount"))
        self.assertEqual((d["verdict"], d["reasons"]), ("UNVERIFIABLE", ["Could not read income_amount from the document."]))

    def test_unrecognised_document_unverifiable(self):
        d, rows = self.run_text("Some other letter\nNothing to see")
        self.assertEqual((d["verdict"], d["reasons"]), ("UNVERIFIABLE", ["Document type not recognised."]))
        self.assertEqual(rows, [])

    def test_qr_mismatch_suspicious_without_asking_issuer(self):
        self.server.shutdown()  # prove the issuer is not asked
        d, _ = self.run_text(printed_text(ACTIVE), qr="INC-1111-1111")
        self.assertEqual(d["verdict"], "SUSPICIOUS")

    def test_issuer_down_unverifiable(self):
        self.server.shutdown()
        self.server.server_close()
        d, _ = self.run_text(printed_text(ACTIVE))
        self.assertEqual((d["verdict"], d["reasons"]), ("UNVERIFIABLE", ["Issuer could not be reached."]))

    def test_wrong_key_shows_the_key_message_not_the_outage_message(self):
        os.environ["ISSUER_KEY_REVENUE_DEPT"] = "pk_wrong"
        d, rows = self.run_text(printed_text(ACTIVE))
        self.assertEqual((d["verdict"], d["reasons"]), ("UNVERIFIABLE", [config.message("key_rejected")]))
        self.assertNotEqual(d["reasons"], [config.message("unreachable")])
        self.assertEqual(rows[0]["issuer"], compare.UNAVAILABLE)

    def test_missing_registry_shows_the_registry_message(self):
        self.records.unlink()
        d, _ = self.run_text(printed_text(ACTIVE))
        self.assertEqual(d["reasons"], [config.message("registry_unavailable")])

    def test_slow_issuer_does_not_block_other_requests(self):
        """The route runs the pipeline via run_in_threadpool; prove the pipeline is safe to run in parallel."""
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(4) as pool:
            verdicts = list(pool.map(lambda _: self.run_text(printed_text(ACTIVE))[0]["verdict"], range(4)))
        self.assertEqual(verdicts, ["VERIFIED"] * 4)

    def test_new_document_type_needs_only_json(self):
        """A second document type defined purely in JSON is detected and extracted with no code change."""
        types = json.loads(SCHEMA.read_text())
        types["document_types"].append({
            "id": "domicile_certificate", "issuer_id": "revenue_dept", "recognize": ["DOMICILE CERTIFICATE"],
            "header_lines": ["DOMICILE CERTIFICATE"], "key_field": "domicile_no", "fields": [
                {"name": "domicile_no", "label": "Domicile No", "value_pattern": "DOM-\\d+", "compare": {"method": "exact"}},
                {"name": "district", "label": "District", "value_pattern": ".+", "compare": {"method": "exact"}}]})
        extra = self.tmp / "types.json"
        extra.write_text(json.dumps(types))
        os.environ["DOCUMENT_TYPES_CONFIG"] = str(extra)
        try:
            text = "DOMICILE CERTIFICATE\nDomicile No: DOM-77\nDistrict: Ernakulam"
            dt = doctypes.detect(text)
            self.assertEqual(dt["id"], "domicile_certificate")
            self.assertEqual(extract.extract_fields(text, dt), {"domicile_no": "DOM-77", "district": "Ernakulam"})
        finally:
            del os.environ["DOCUMENT_TYPES_CONFIG"]


if __name__ == "__main__":
    unittest.main()
