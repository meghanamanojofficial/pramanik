#!/usr/bin/env python3
"""Start the whole Pramanik demo with one command (from the repo root):

    python run_all.py            # create keys if missing, start both services, open on http://localhost:8001
    python run_all.py --reload   # same, with auto-reload for development
    python run_all.py --test     # start both, generate the test PDFs, run every test, then stop

Ports are fixed: issuer service 8002 (backend/config/issuers.json points there), Pramanik 8001.
Press Ctrl+C to stop both.
"""
import argparse
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BACKEND, ISSUER = ROOT / "backend", ROOT / "issuer_service"
ISSUER_URL, BACKEND_URL = "http://127.0.0.1:8002", "http://127.0.0.1:8001"


def ensure_keys() -> None:
    """API keys, QR signing keys and the ledger secret. Signing keys are per machine, so the demo
    documents (which carry signed QR codes) are regenerated whenever new keys are made."""
    sys.path.insert(0, str(ISSUER))
    import setup_keys

    have_all = ((BACKEND / ".env").exists() and (ISSUER / "keys.json").exists()
                and (BACKEND / "config" / "issuer_keys.json").exists()
                and "PRAMANIK_FINGERPRINT_KEY" in setup_keys.read_env(BACKEND / ".env"))
    if have_all:
        return
    print("First run: creating keys (never committed)...")
    setup_keys.main()
    setup_keys.setup_signing()
    setup_keys.setup_fingerprint_key()
    for script in ("make_test_pdfs.py", "make_scan_samples.py"):
        subprocess.call([sys.executable, f"tools/{script}"], cwd=BACKEND)


def wait_for(url: str, name: str, proc: subprocess.Popen, seconds: int = 30) -> None:
    deadline = time.time() + seconds
    while time.time() < deadline:
        if proc.poll() is not None:
            sys.exit(f"{name} exited early (code {proc.returncode}). Is it installed? pip install -r backend/requirements.txt")
        try:
            with urllib.request.urlopen(url + "/health", timeout=2):
                return
        except (urllib.error.URLError, OSError):
            time.sleep(0.5)
    sys.exit(f"{name} did not start within {seconds}s")


def serve(cwd: Path, app: str, port: int, reload: bool) -> subprocess.Popen:
    cmd = [sys.executable, "-m", "uvicorn", app, "--port", str(port)]
    if reload:
        cmd.append("--reload")
    return subprocess.Popen(cmd, cwd=cwd)  # inherits os.environ (see main(): --test gives it a fresh ledger)


def stop(procs) -> None:
    for p in procs:
        if p.poll() is None:
            p.terminate()
    for p in procs:
        try:
            p.wait(timeout=10)
        except subprocess.TimeoutExpired:
            p.kill()


def run_tests() -> int:
    steps = [
        ("generate test PDFs", [sys.executable, "tools/make_test_pdfs.py"], BACKEND),
        ("generate sample scans", [sys.executable, "tools/make_scan_samples.py"], BACKEND),
        ("issuer + pipeline unit tests", [sys.executable, "-m", "unittest", "discover", "-s", "issuer_service/tests"], ROOT),
        ("scan, signing and ledger unit tests", [sys.executable, "-m", "unittest", "discover", "-s", "backend/tests", "-p", "test_*.py"], ROOT),
        ("acceptance tests", [sys.executable, "tests/run_acceptance.py"], BACKEND),
    ]
    failed = 0
    for label, cmd, cwd in steps:
        print(f"\n=== {label} ===")
        code = subprocess.call(cmd, cwd=cwd)
        if code:
            print(f"!!! {label} failed (exit {code})")
            failed += 1
    return failed


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--reload", action="store_true", help="auto-reload on code changes")
    ap.add_argument("--test", action="store_true", help="run all tests against the started services, then stop")
    args = ap.parse_args()

    ensure_keys()
    if args.test:  # the acceptance tests expect an empty reuse ledger
        import tempfile
        os.environ["DATABASE_URL"] = "sqlite:///" + (Path(tempfile.mkdtemp()) / "acceptance.db").as_posix()
    procs = []
    try:
        issuer = serve(ISSUER, "main:app", 8002, args.reload)
        procs.append(issuer)
        wait_for(ISSUER_URL, "issuer service", issuer)
        backend = serve(BACKEND, "app.main:app", 8001, args.reload)
        procs.append(backend)
        wait_for(BACKEND_URL, "Pramanik backend", backend)

        if args.test:
            failed = run_tests()
            print("\nALL TESTS PASSED" if not failed else f"\n{failed} test step(s) FAILED")
            return 1 if failed else 0

        print(f"\nPramanik is running: {BACKEND_URL}   (issuer service: {ISSUER_URL})\nCtrl+C to stop.")
        while all(p.poll() is None for p in procs):
            time.sleep(1)
        return 1
    except KeyboardInterrupt:
        return 0
    finally:
        stop(procs)


if __name__ == "__main__":
    sys.exit(main())
