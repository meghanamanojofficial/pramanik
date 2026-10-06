"""Acceptance tests. Needs BOTH servers running (issuer service on 8002, Pramanik on 8001).
Run from backend/ after `python tools/make_test_pdfs.py`:  python tests/run_acceptance.py

Test inputs live in config/test_cases.json; field names come from config/document_types.json.
Set BASE_URL to test a different host (default comes from test_cases.json).

The tests assume an EMPTY reuse ledger (a certificate already checked in another case is flagged, which is
correct but would change the expected verdicts). `python run_all.py --test` starts the services with a fresh one;
when running this by hand, start the backend with DATABASE_URL=sqlite:///<a new file> and pass the same value here.
"""
import json
import os
import sys
import tempfile
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
CFG = json.loads((ROOT / "config" / "test_cases.json").read_text(encoding="utf-8"))
UI = json.loads((ROOT / "config" / "ui.json").read_text(encoding="utf-8"))
MSG = UI["messages"]
SCHEMA = json.loads((ROOT / "config" / "document_types.json").read_text(encoding="utf-8"))["document_types"]
DOC = next(t for t in SCHEMA if t["id"] == CFG["document_type"])

BASE = os.environ.get("BASE_URL", CFG["base_url"])
TESTS = ROOT.parent / "demo_docs" / "pdfs"
SCANS = ROOT.parent / "demo_docs" / "scans"
RECORDS = ROOT / CFG["records_file"]
AUDIT = ROOT / CFG["audit_file"]
CASE_ID = CFG["leak_check_case_id"]
OFFICER = CFG["officer_id"]
TAMPER_FIELD, TAMPER_BY = CFG["tamper"]["field"], CFG["tamper"]["increase"]
N_FIELDS = len(DOC["fields"])

results: list[tuple[str, bool, str]] = []


def record(name: str, ok: bool, note: str = "") -> None:
    results.append((name, ok, note))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  ({note})" if note and not ok else ""))


def post(pdf: Path | None = None, *, case_id: str = CASE_ID, content: bytes | None = None, filename: str | None = None,
         fresh: bool = False):
    data = {"officer_id": OFFICER, "case_id": case_id, "purpose": "acceptance"}
    if fresh:
        data["fresh"] = "1"
    if pdf is not None:  # any file: the server decides what it is from its bytes, not its name
        content, filename = pdf.read_bytes(), pdf.name
    files = {"file": (filename or "file.pdf", content or b"", "application/octet-stream")}
    return requests.post(f"{BASE}/verify", data=data, files=files, timeout=120)


def audit_lines() -> list[str]:
    return AUDIT.read_text(encoding="utf-8").splitlines() if AUDIT.exists() else []


def snapshot(paths: list[Path]) -> set[str]:
    seen: set[str] = set()
    skip = {"__pycache__", ".git", "venv", ".venv", "node_modules"}
    for base in paths:
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [d for d in dirnames if d not in skip]
            for f in filenames:
                p = Path(dirpath) / f
                if p != AUDIT:
                    seen.add(str(p))
    return seen


def edited_value_absent(body: dict, note: dict) -> bool:
    row = next((r for r in body["fields"] if r["field"] == TAMPER_FIELD), {})
    return bool(row.get("document")) and row["document"] not in note["detail"]


def main() -> int:
    records = json.loads(RECORDS.read_text(encoding="utf-8"))
    active = next(r for r in records if r["status"] == "active")

    # 1. health
    h = requests.get(f"{BASE}/health", timeout=10).json()
    record("1  GET /health", h == {"status": "ok", "records_loaded": len(records)}, str(h))
    caps = requests.get(f"{BASE}/api/capabilities", timeout=10).json()
    record("1b GET /api/capabilities (OCR, reuse ledger and QR keys available)",
           caps.get("ocr") is True and caps.get("reuse_ledger") is True and caps.get("qr_signature_keys", 0) >= 1, str(caps))

    # 2. each PDF gives the expected verdict and key reason
    expected = {
        "genuine.pdf": ("VERIFIED", MSG["all_match"]),
        "edited_amount.pdf": ("MISMATCH", MSG["field_mismatch"].format(field=TAMPER_FIELD)),
        "unknown_number.pdf": ("SUSPICIOUS", MSG["not_found"]),
        "revoked.pdf": ("SUSPICIOUS", MSG["status_not_valid"].format(status="revoked")),
        "plain_qr.pdf": ("VERIFIED", MSG["all_match"]),
        "forged_signature.pdf": ("MATCHES_RECORD_INTEGRITY_CONCERNS", MSG["qr_sig_bad_signature"]),
        "scanned_genuine.pdf": ("VERIFIED", MSG["all_match"]),  # image-only PDF, read by OCR
    }
    for name, (verdict, reason) in expected.items():
        pdf = TESTS / name
        if not pdf.exists():
            record(f"2  {name} exists", False, "missing: run `python tools/make_test_pdfs.py` from backend/")
            continue
        body = post(pdf).json()
        record(f"2  {name} -> {verdict}", body.get("verdict") == verdict and reason in body.get("reasons", []),
               f"got {body.get('verdict')} {body.get('reasons')}")

    # 2b. photos and scans: same rules, same verdicts (one case id for all, so the reuse check stays quiet)
    scan_expected = {
        "genuine_clean.jpg": ("VERIFIED", MSG["all_match"]),
        "genuine_photographed.jpg": ("VERIFIED", MSG["all_match"]),
        "genuine_phone_rotated.jpg": ("VERIFIED", MSG["all_match"]),
        "tampered_amount.jpg": ("MISMATCH", MSG["field_mismatch"].format(field=TAMPER_FIELD)),
        "unknown_number.jpg": ("SUSPICIOUS", MSG["not_found"]),
        "revoked.jpg": ("SUSPICIOUS", MSG["status_not_valid"].format(status="revoked")),
        "forged_signature.jpg": ("MATCHES_RECORD_INTEGRITY_CONCERNS", MSG["qr_sig_bad_signature"]),
        "genuine_blurry.jpg": ("RESCAN", MSG["scan_blur"]),
        "genuine_dark.jpg": ("RESCAN", MSG["scan_dark"]),
        "unreadable_noise.jpg": ("INCONCLUSIVE", None),
    }
    for name, (verdict, reason) in scan_expected.items():
        img = SCANS / name
        if not img.exists():
            record(f"2b {name} exists", False, "missing: run `python tools/make_scan_samples.py` from backend/")
            continue
        body = post(img).json()
        ok = body.get("verdict") == verdict and (reason is None or reason in body.get("reasons", []))
        if verdict in ("RESCAN", "INCONCLUSIVE"):  # nothing is claimed about the document, so the issuer is not asked
            ok = ok and body.get("fields") == [] and bool(body.get("rescan_guidance"))
        record(f"2b {name} -> {verdict}", ok, f"got {body.get('verdict')} {body.get('reasons')}")

    # 2c. an edited document contradicts its own issuer-signed QR, and the response says so (without values)
    body = post(TESTS / "edited_amount.pdf").json()
    note = next((x for x in body.get("signals", []) if x["name"] == "signed_qr_field_mismatch"), None)
    record("2c edited amount flagged against its own signed QR, value not repeated",
           note is not None and edited_value_absent(body, note), str(note))

    # 2d. risk score: advice that follows the verdict, and honest "not assessed" when nothing was judged
    risks = {name: post(path).json().get("risk", {}) for name, path in
             (("genuine", TESTS / "genuine.pdf"), ("edited", TESTS / "edited_amount.pdf"),
              ("forged", TESTS / "forged_signature.pdf"), ("blurry", SCANS / "genuine_blurry.jpg"))}
    record("2d risk: genuine low, forged-QR medium or higher, edited high, blurry not assessed",
           risks["genuine"].get("level") == "low" and risks["edited"].get("level") == "high"
           and risks["forged"].get("level") in ("medium", "high")
           and risks["blurry"].get("level") == "not_assessed" and risks["blurry"].get("score") is None
           and risks["edited"].get("factors"), str({k: (v.get("score"), v.get("level")) for k, v in risks.items()}))

    # 2e. issuer-answer cache: a repeat check reuses the issuer's answer; fresh=1 and any edit do not
    again = post(TESTS / "genuine.pdf").json()
    record("2e repeat check reuses the issuer's recent answer (still VERIFIED)",
           again.get("verdict") == "VERIFIED" and again["checks"].get("issuer_lookup") == "cache", str(again.get("checks")))
    live = post(TESTS / "genuine.pdf", fresh=True).json()
    record("2e 'ask the issuer again' forces a live lookup", live["checks"].get("issuer_lookup") == "live", str(live.get("checks")))
    # (the genuine certificate's cached "all fields match" must never leak onto an edited copy of it)
    edited_check = post(TESTS / "edited_amount.pdf").json()
    row = next((r for r in edited_check.get("fields", []) if r["field"] == TAMPER_FIELD), {})
    record("2e an edited document never inherits the genuine one's cached answer",
           edited_check.get("verdict") == "MISMATCH" and row.get("match") is False, str(edited_check.get("verdict")))

    # 3. edited field: flagged, shows the edited value, and the issuer's real value is NOT disclosed
    body = post(TESTS / "edited_amount.pdf").json()
    row = next((r for r in body.get("fields", []) if r["field"] == TAMPER_FIELD), {})
    edited = str(int(active[TAMPER_FIELD]) + TAMPER_BY)
    record("3  edited field row, issuer value not disclosed",
           row.get("match") is False and row.get("document") == edited
           and row.get("issuer") != active[TAMPER_FIELD]
           and body.get("coverage") == f"{N_FIELDS - 1} of {N_FIELDS} printed fields confirmed with issuer", str(row))

    # 4. empty case id
    r = requests.post(f"{BASE}/verify", data={"officer_id": OFFICER, "case_id": "", "purpose": "x"},
                      files={"file": ("a.pdf", (TESTS / "genuine.pdf").read_bytes(), "application/pdf")}, timeout=30)
    record("4  empty case_id -> 400", r.status_code == 400, str(r.status_code))

    # 5. non-PDF
    r = post(content=b"hello, not a pdf", filename="note.txt")
    record("5  neither PDF nor image -> 400", r.status_code == 400 and r.json().get("detail") == MSG["unsupported_file"], str(r.status_code))

    # 6. audit log: N requests -> N lines, no leaked content (a photo counts the same as a PDF)
    before = len(audit_lines())
    n = 0
    for path in (TESTS / "genuine.pdf", TESTS / "edited_amount.pdf", TESTS / "unknown_number.pdf",
                 SCANS / "genuine_clean.jpg", SCANS / "tampered_amount.jpg"):
        post(path)
        n += 1
    new = audit_lines()[before:]
    banned = [str(active[f]) for f in CFG["leak_check_fields"]] + [edited, CASE_ID]
    leaked = [b for b in banned if any(b in line for line in new)]
    record("6  audit log lines, no leaks", len(new) == n and not leaked, f"lines={len(new)}/{n} leaked={leaked}")

    # 7. no new files in the project or system temp directory
    watch = [ROOT, Path(tempfile.gettempdir())]
    before_files = snapshot(watch)
    post(TESTS / "genuine.pdf")
    post(TESTS / "edited_amount.pdf")
    post(SCANS / "genuine_photographed.jpg")  # image processing must not write temp files either
    after_files = snapshot(watch)
    record("7  no files written during requests", after_files <= before_files, str(sorted(after_files - before_files)[:5]))

    # 7b. the same certificate in a *different* case is flagged; the same case again is not
    body = post(TESTS / "genuine.pdf", case_id="CASE-REUSE-OTHER").json()
    record("7b genuine certificate presented in another case -> VERIFIED_WITH_WARNINGS",
           body.get("verdict") == "VERIFIED_WITH_WARNINGS" and body.get("checks", {}).get("reuse_check") == "flagged",
           str(body.get("verdict")))

    # 7d. the ledger database holds no readable names, numbers, amounts or case ids
    url = os.environ.get("DATABASE_URL", "")
    db = Path(url[len("sqlite:///"):]) if url.startswith("sqlite:///") else ROOT / "data" / "pramanik.db"
    blob = db.read_bytes() if db.exists() else b""
    banned_db = [str(active[f]).encode() for f in ("certificate_number", "holder_name")] + [CASE_ID.encode(), b"CASE-REUSE-OTHER"]
    record("7d ledger database stores no readable content", bool(blob) and not any(b in blob for b in banned_db),
           "database missing" if not blob else "")

    # 8. issuer's records file missing -> issuer cannot answer
    backup = RECORDS.with_suffix(".json.bak")
    RECORDS.rename(backup)
    try:
        body = post(TESTS / "genuine.pdf", fresh=True).json()  # fresh: a cached answer would (correctly) still be served
        record("8  records file removed -> UNVERIFIABLE with the registry reason (not 'could not be reached')",
               body.get("verdict") == "UNVERIFIABLE" and MSG["registry_unavailable"] in body.get("reasons", []),
               str(body.get("reasons")))
    finally:
        backup.rename(RECORDS)

    failed = [n for n, ok, _ in results if not ok]
    print(f"\n{len(results) - len(failed)} passed, {len(failed)} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
