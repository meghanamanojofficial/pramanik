"""Accounts, sessions, access rules, security headers, history, and the shipped pages."""
import json
import os
import re
import unittest
import warnings

from support import ROOT, Isolated  # noqa: F401  (sets import paths)

warnings.filterwarnings("ignore")
from starlette.testclient import TestClient  # noqa: E402

from app import security  # noqa: E402
from app.main import app  # noqa: E402
from app.services import accounts, audit, throttle  # noqa: E402

PW = "a-long-enough-pass"
FRONTEND = ROOT / "frontend"


class Api(Isolated):
    def setUp(self):
        super().setUp()
        for k in ("PRAMANIK_SIGNUP", "PRAMANIK_SIGNUP_CODE", "PRAMANIK_COOKIE_SECURE", "PRAMANIK_SESSION_HOURS"):
            self._env.setdefault(k, os.environ.get(k))
            os.environ.pop(k, None)
        throttle.reset()
        self.client = TestClient(app, base_url="http://testserver", follow_redirects=False)
        self.client.__enter__()
        self.audit_file = self.tmp / "audit.log"
        self._real_audit = audit.AUDIT_FILE
        audit.AUDIT_FILE = self.audit_file

    def tearDown(self):
        audit.AUDIT_FILE = self._real_audit
        self.client.__exit__(None, None, None)
        super().tearDown()

    def signup(self, email="o@dept.gov.in", client=None, **extra):
        return (client or self.client).post("/api/auth/signup", json={"email": email, "password": PW, **extra})

    def complete(self, officer_id="OFC-1", client=None):
        return (client or self.client).put("/api/auth/profile", json={"full_name": "Asha Menon", "officer_id": officer_id, "role": "Officer"})

    def signed_in(self, email="o@dept.gov.in", officer_id="OFC-1"):
        self.signup(email); self.complete(officer_id)


class AccountTests(Api):
    def test_password_hash_is_salted_and_verifies(self):
        a, b = accounts.hash_password(PW), accounts.hash_password(PW)
        self.assertNotEqual(a, b)
        self.assertTrue(accounts.check_password(PW, a) and not accounts.check_password(PW + "x", a))
        self.assertFalse(accounts.check_password(PW, "garbage"))
        self.assertNotIn(PW, a)

    def test_signup_login_logout_me(self):
        r = self.signup()
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.json()["user"]["profile_complete"])
        self.assertEqual(self.client.get("/api/auth/me").json()["user"]["email"], "o@dept.gov.in")
        self.client.post("/api/auth/logout")
        self.assertEqual(self.client.get("/api/auth/me").status_code, 401)
        self.assertEqual(self.client.post("/api/auth/login", json={"email": "O@Dept.gov.in", "password": PW}).status_code, 200)

    def test_cookie_is_httponly_samesite_and_secure_only_over_https(self):
        header = self.signup().headers["set-cookie"].lower()
        self.assertIn("httponly", header); self.assertIn("samesite=lax", header); self.assertNotIn("secure", header.replace("samesite", ""))
        self.client.post("/api/auth/logout")
        h = self.client.post("/api/auth/login", json={"email": "o@dept.gov.in", "password": PW}, headers={"X-Forwarded-Proto": "https"}).headers["set-cookie"].lower()
        self.assertIn("; secure", h)

    def test_validation(self):
        bad = lambda email, pw: self.client.post("/api/auth/signup", json={"email": email, "password": pw}).status_code
        self.assertEqual(bad("not-an-email", PW), 400)
        self.assertEqual(bad("a@b.gov.in", "short"), 400)
        self.assertEqual(bad("a@b.gov.in", "x" * 129), 400)
        self.assertEqual(self.signup().status_code, 200)
        self.assertEqual(self.signup("O@DEPT.gov.in").status_code, 409)  # same address, any case

    def test_wrong_password_and_unknown_email_look_the_same(self):
        self.signup()
        a = self.client.post("/api/auth/login", json={"email": "o@dept.gov.in", "password": "wrong-password"})
        b = self.client.post("/api/auth/login", json={"email": "nobody@dept.gov.in", "password": "wrong-password"})
        self.assertEqual((a.status_code, a.json()), (b.status_code, b.json()))

    def test_repeated_failures_are_throttled_and_a_success_resets_the_account_counter(self):
        self.signup()
        self.client.post("/api/auth/logout")
        for _ in range(7):
            self.client.post("/api/auth/login", json={"email": "o@dept.gov.in", "password": "wrong-password"})
        self.assertEqual(self.client.post("/api/auth/login", json={"email": "o@dept.gov.in", "password": PW}).status_code, 200)
        throttle.reset()
        for _ in range(8):
            self.client.post("/api/auth/login", json={"email": "o@dept.gov.in", "password": "wrong-password"})
        self.assertEqual(self.client.post("/api/auth/login", json={"email": "o@dept.gov.in", "password": PW}).status_code, 429)

    def test_logout_ends_the_session_on_the_server(self):
        self.signup()
        stolen = self.client.cookies.get(security.COOKIE_NAME)
        self.client.post("/api/auth/logout")
        thief = TestClient(app, base_url="http://testserver")
        thief.cookies.set(security.COOKIE_NAME, stolen)
        self.assertEqual(thief.get("/api/auth/me").status_code, 401)

    def test_sessions_expire_and_only_a_hash_is_stored(self):
        self.signup()
        token = self.client.cookies.get(security.COOKIE_NAME)
        from sqlalchemy import text
        from app.services import ledger
        with ledger._get_engine().begin() as db:
            stored = [r[0] for r in db.execute(text("SELECT token_hash FROM sessions"))]
            db.execute(text("UPDATE sessions SET expires_at = 1"))
        self.assertNotIn(token, stored)
        self.assertEqual(self.client.get("/api/auth/me").status_code, 401)

    def test_officer_ids_are_unique_and_validated(self):
        self.signed_in("a@dept.gov.in", "OFC-1")
        other = TestClient(app, base_url="http://testserver")
        self.signup("b@dept.gov.in", client=other)
        r = self.complete("OFC-1", client=other)
        self.assertEqual(r.status_code, 409)
        self.assertEqual(self.complete("bad id!").status_code, 400)
        self.assertEqual(self.complete("OFC-2", client=other).status_code, 200)

    def test_signup_policy(self):
        self.assertEqual(self.client.get("/api/auth/options").json()["signup"], "open")
        os.environ["PRAMANIK_SIGNUP_CODE"] = "letmein-123"
        self.assertEqual(self.client.get("/api/auth/options").json()["signup"], "code")
        self.assertEqual(self.signup().status_code, 403)
        self.assertEqual(self.signup(signup_code="wrong").status_code, 403)
        self.assertEqual(self.signup(signup_code="letmein-123").status_code, 200)
        self.client.post("/api/auth/logout")
        os.environ["PRAMANIK_SIGNUP"] = "closed"
        self.assertEqual(self.signup("c@dept.gov.in", signup_code="letmein-123").status_code, 403)
        self.assertEqual(self.client.post("/api/auth/login", json={"email": "o@dept.gov.in", "password": PW}).status_code, 200)  # login still works


class AccessTests(Api):
    def test_verify_and_history_need_a_signed_in_officer_with_a_profile(self):
        files = {"file": ("a.pdf", b"%PDF-1.4")}
        self.assertEqual(self.client.post("/verify", data={"case_id": "c"}, files=files).status_code, 401)
        self.assertEqual(self.client.get("/api/history").status_code, 401)
        self.signup()
        self.assertEqual(self.client.post("/verify", data={"case_id": "c"}, files=files).status_code, 403)
        self.assertEqual(self.client.get("/api/history").status_code, 403)

    def test_pages_follow_the_session(self):
        loc = lambda path: (lambda r: (r.status_code, r.headers.get("location")))(self.client.get(path))
        self.assertEqual(loc("/"), (303, "/app/signin.html"))
        self.assertEqual(loc("/app/maindash.html"), (303, "/app/signin.html"))
        self.assertEqual(loc("/app/creds.html"), (303, "/app/signin.html"))
        self.assertEqual(self.client.get("/app/signin.html").status_code, 200)
        self.signup()
        self.assertEqual(loc("/"), (303, "/app/creds.html"))
        self.assertEqual(loc("/app/maindash.html"), (303, "/app/creds.html"))
        self.assertEqual(self.client.get("/app/creds.html").status_code, 200)
        self.complete()
        self.assertEqual(loc("/"), (303, "/app/maindash.html"))
        for page in ("maindash.html", "analysing.html", "result.html"):
            self.assertEqual(self.client.get(f"/app/{page}").status_code, 200, page)
        self.assertEqual(loc("/app/signin.html"), (303, "/app/maindash.html"))

    def test_the_plain_fallback_page_follows_the_same_rules(self):
        self.assertEqual(self.client.get("/classic").headers["location"], "/app/signin.html")
        self.signed_in()
        page = self.client.get("/classic")
        self.assertEqual(page.status_code, 200)
        self.assertIn("'unsafe-inline'", page.headers["content-security-policy"].split("script-src")[1].split(";")[0])  # it has an inline script
        self.assertNotIn("frame-ancestors 'self'", page.headers["content-security-policy"])

    def test_only_listed_pages_are_served(self):
        for path in ("/app/../config/ui.json", "/app/package.json", "/app/build.mjs", "/app/tailwind/base.css", "/app/..%2fbackend%2f.env"):
            self.assertNotEqual(self.client.get(path).status_code, 200, path)
        self.assertEqual(self.client.get("/app/js/api.js").status_code, 200)
        self.assertEqual(self.client.get("/app/js/../../backend/.env").status_code, 404)

    def test_other_sites_cannot_make_requests_for_the_officer(self):
        self.signed_in()
        for origin in ("http://evil.example", "https://evil.example:8443"):
            self.assertEqual(self.client.put("/api/auth/profile", json={"full_name": "X", "officer_id": "OFC-9"}, headers={"Origin": origin}).status_code, 403, origin)
        self.assertEqual(self.client.put("/api/auth/profile", json={"full_name": "X", "officer_id": "OFC-9"}, headers={"Origin": "http://testserver"}).status_code, 200)

    def test_headers(self):
        page = self.client.get("/app/signin.html")
        csp = page.headers["content-security-policy"]
        self.assertIn("script-src 'self';", csp); self.assertNotIn("unsafe-eval", csp); self.assertIn("frame-ancestors 'none'", csp)
        self.assertEqual(page.headers["cache-control"], "no-store")
        for h, v in (("x-content-type-options", "nosniff"), ("x-frame-options", "DENY"), ("referrer-policy", "no-referrer")):
            self.assertEqual(page.headers[h], v)
        self.assertEqual(self.client.get("/api/auth/options").headers["cache-control"], "no-store")
        self.assertNotIn("strict-transport-security", page.headers)
        self.assertIn("strict-transport-security", self.client.get("/app/signin.html", headers={"X-Forwarded-Proto": "https"}).headers)

    def test_history_is_only_this_officers_and_never_content(self):
        self.signed_in("a@dept.gov.in", "OFC-1")
        for officer, source, verdict in (("OFC-1", "authenticated_account", "VERIFIED"), ("OFC-2", "authenticated_account", "MISMATCH"),
                                         ("OFC-1", "self_reported", "SUSPICIOUS"), ("OFC-1", "authenticated_account", "RESCAN")):
            audit.write_audit("h" * 64, verdict, "direct_issuer", "t", "2026-01-01T00:00:00Z", "pdf", "live", source) if False else None
            line = {"doc_hash": "h" * 64, "verdict": verdict, "route": "none", "input_type": "pdf", "issuer_source": "none",
                    "officer_id": officer, "officer_id_source": source, "timestamp": "2026-01-01T00:00:00Z"}
            with self.audit_file.open("a", encoding="utf-8") as f:
                f.write(json.dumps(line) + "\n")
            with self.audit_file.open("a", encoding="utf-8") as f:
                f.write("this line is not json\n")
        got = self.client.get("/api/history").json()
        self.assertEqual([g["verdict"] for g in got], ["RESCAN", "VERIFIED"])  # newest first, own entries, real accounts only
        self.assertEqual(set(got[0]), {"verdict", "route", "input_type", "doc_hash", "officer_id", "timestamp"})
        self.assertEqual(len(self.client.get("/api/history?limit=1").json()), 1)

    def test_audit_recent_reads_only_the_tail_of_a_big_file(self):
        with self.audit_file.open("w", encoding="utf-8") as f:
            for i in range(3000):
                f.write(json.dumps({"doc_hash": f"{i:064d}", "verdict": "VERIFIED", "officer_id": "OFC-1", "officer_id_source": "authenticated_account", "timestamp": "t"}) + "\n")
        got = audit.recent("OFC-1", 5, tail_bytes=20000)
        self.assertEqual(len(got), 5)
        self.assertEqual(got[0]["doc_hash"], f"{2999:064d}")


class ShippedPagesTests(unittest.TestCase):
    pages = ["signin", "creds", "maindash", "analysing", "result"]

    def test_no_inline_scripts_no_external_requests_no_inline_handlers(self):
        for page in self.pages:
            html = (FRONTEND / f"{page}.html").read_text(encoding="utf-8")
            self.assertEqual(re.findall(r"<script(?![^>]*\bsrc=)[^>]*>", html), [], f"{page}: inline script")
            self.assertEqual(re.findall(r"\son(?:click|change|submit|load|error)=", html), [], f"{page}: inline handler")
            self.assertEqual(re.findall(r'(?:src|href)="https?://[^"]+', html), [], f"{page}: external resource")
            self.assertEqual(re.findall(r"cdn\.tailwindcss|googleapis|gstatic", html), [], page)

    def test_every_referenced_file_exists(self):
        for page in self.pages:
            html = (FRONTEND / f"{page}.html").read_text(encoding="utf-8")
            for ref in re.findall(r'(?:src|href)="((?:js|css)/[^"]+)"', html):
                self.assertTrue((FRONTEND / ref).exists(), f"{page}: {ref}")

    def test_the_prototype_scaffolding_is_gone(self):
        blob = "".join((FRONTEND / f"{n}.html").read_text(encoding="utf-8") + (FRONTEND / "js" / f"{n}.js").read_text(encoding="utf-8") for n in self.pages)
        blob += (FRONTEND / "js" / "api.js").read_text(encoding="utf-8") + (FRONTEND / "js" / "ui.js").read_text(encoding="utf-8")
        for needle in ("meghana", "Meghana", "Pramanik2026", "setVerificationState", "paradox1212", "Auth Net",
                       "automated provisioning", "degree_certificate", "innerHTML", "eval(", "document.write"):
            self.assertFalse(needle in blob, f"prototype leftover found: {needle!r}")
        # the one allowed mention of a sample officer ID is the format hint in the profile form
        self.assertEqual(blob.count("OFC-4921"), blob.count('placeholder="e.g. OFC-4921"'), "a sample officer ID is used as data")

    def test_server_page_list_matches_the_files(self):
        from app.routers import pages
        for name in pages.PUBLIC | pages.NEEDS_LOGIN | pages.NEEDS_PROFILE:
            self.assertTrue((FRONTEND / name).exists(), name)


if __name__ == "__main__":
    unittest.main()
