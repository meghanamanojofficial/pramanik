"""Acceptance tests. Needs a running server:  uvicorn app.main:app --reload
Run from backend/ after `python tools/make_test_pdfs.py`:  python tests/run_acceptance.py
Set BASE_URL to test a different host (default http://localhost:8000).
"""
import json
import os
import sys
import tempfile
from pathlib import Path

import requests

BASE = os.environ.get("BASE_URL", "http://localhost:8000")
ROOT = Path(__file__).resolve().parents[1]
TESTS = ROOT.parent / "demo_docs" / "pdfs"
RECORDS = ROOT / "data" / "mock_records.json"
AUDIT = ROOT / "audit.log"
CASE_ID = "CASE-LEAKCHECK-77123"

results: list[tuple[str, bool, str]] = []


def record(name: str, ok: bool, note: str = "") -> None:
    results.append((name, ok, note))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  ({note})" if note and not ok else ""))


def post(pdf: Path | None = None, *, case_id: str = CASE_ID, content: bytes | None = None, filename: str | None = None):
    data = {"officer_id": "OFF-TEST", "case_id": case_id, "purpose": "acceptance"}
    if pdf is not None:
        content, filename = pdf.read_bytes(), pdf.name
    files = {"file": (filename or "file.pdf", content or b"", "application/pdf")}
    return requests.post(f"{BASE}/verify", data=data, files=files, timeout=30)


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


def main() -> int:
    records = json.loads(RECORDS.read_text(encoding="utf-8"))
    active = next(r for r in records if r["status"] == "active")

    # 1. health
    h = requests.get(f"{BASE}/health", timeout=10).json()
    record("1  GET /health", h == {"status": "ok", "records_loaded": len(records)}, str(h))

    # 2. each PDF gives the expected verdict and key reason
    expected = {
        "genuine.pdf": ("VERIFIED", "All printed fields match the issuer record."),
        "edited_amount.pdf": ("TAMPERED", "income_amount on the document does not match the issuer record."),
        "unknown_number.pdf": ("SUSPICIOUS", "Issuer has no record of this certificate number."),
        "revoked.pdf": ("SUSPICIOUS", "Issuer lists this certificate as revoked."),
    }
    sent = 0
    for name, (verdict, reason) in expected.items():
        pdf = TESTS / name
        if not pdf.exists():
            print(f"SKIP  2  {name} (not generated; probably no record of that kind)")
            continue
        body = post(pdf).json()
        sent += 1
        record(f"2  {name} -> {verdict}", body.get("verdict") == verdict and reason in body.get("reasons", []),
               f"got {body.get('verdict')} {body.get('reasons')}")

    # 3. edited amount details
    body = post(TESTS / "edited_amount.pdf").json()
    sent += 1
    row = next((r for r in body.get("fields", []) if r["field"] == "income_amount"), {})
    edited = str(int(active["income_amount"]) + 100000)
    record("3  edited_amount field row",
           row.get("match") is False and row.get("document") == edited and row.get("issuer") == active["income_amount"]
           and body.get("coverage") == "3 of 4 printed fields confirmed with issuer", str(row))

    # 4. empty case id
    r = requests.post(f"{BASE}/verify", data={"officer_id": "OFF-TEST", "case_id": "", "purpose": "x"},
                      files={"file": ("a.pdf", (TESTS / "genuine.pdf").read_bytes(), "application/pdf")}, timeout=30)
    record("4  empty case_id -> 400", r.status_code == 400, str(r.status_code))

    # 5. non-PDF
    r = post(content=b"hello, not a pdf", filename="note.txt")
    record("5  non-PDF -> 400", r.status_code == 400 and r.json().get("detail") == "Upload a text-based PDF.", str(r.status_code))

    # 6. audit log: N requests -> N lines, no leaked content
    before = len(audit_lines())
    n = 0
    for name in ("genuine.pdf", "edited_amount.pdf", "unknown_number.pdf"):
        post(TESTS / name)
        n += 1
    new = audit_lines()[before:]
    banned = [active["holder_name"], active["income_amount"], str(int(active["income_amount"]) + 100000), CASE_ID]
    leaked = [b for b in banned if any(b in line for line in new)]
    record("6  audit log lines, no leaks", len(new) == n and not leaked, f"lines={len(new)}/{n} leaked={leaked}")

    # 7. no new files in the project or system temp directory
    watch = [ROOT, Path(tempfile.gettempdir())]
    before_files = snapshot(watch)
    post(TESTS / "genuine.pdf")
    post(TESTS / "edited_amount.pdf")
    after_files = snapshot(watch)
    record("7  no files written during requests", after_files <= before_files, str(sorted(after_files - before_files)[:5]))

    # 8. records file missing -> issuer unreachable
    backup = RECORDS.with_suffix(".json.bak")
    RECORDS.rename(backup)
    try:
        body = post(TESTS / "genuine.pdf").json()
        record("8  records file removed -> UNVERIFIABLE",
               body.get("verdict") == "UNVERIFIABLE" and "Issuer could not be reached." in body.get("reasons", []),
               str(body.get("reasons")))
    finally:
        backup.rename(RECORDS)

    failed = [n for n, ok, _ in results if not ok]
    print(f"\n{len(results) - len(failed)} passed, {len(failed)} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
