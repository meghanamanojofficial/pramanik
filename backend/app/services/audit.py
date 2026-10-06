"""Append-only audit log. One JSON line per request, with no content, names, fields or case IDs.

officer_id is the one on the signed-in account (accounts must have a unique officer ID), and each line records
where it came from. The log shows what was checked and when, and by which account; it never holds content."""
import json
import threading
from pathlib import Path

OFFICER_ID_SOURCE = "authenticated_account"
AUDIT_FILE = Path(__file__).resolve().parents[2] / "audit.log"
_lock = threading.Lock()


def write_audit(doc_hash: str, verdict: str, route: str, officer_id: str, timestamp: str,
                input_type: str = "pdf", issuer_source: str = "none",
                officer_source: str = OFFICER_ID_SOURCE) -> None:
    line = json.dumps({"doc_hash": doc_hash, "verdict": verdict, "route": route, "input_type": input_type, "issuer_source": issuer_source,
                       "officer_id": officer_id, "officer_id_source": officer_source,
                       "timestamp": timestamp}, separators=(",", ":"))
    with _lock, AUDIT_FILE.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def recent(officer_id: str, limit: int = 20, tail_bytes: int = 4 * 1024 * 1024) -> list[dict]:
    """The newest entries written under this account's officer ID, newest first (reads only the end of the file)."""
    if not officer_id or not AUDIT_FILE.exists():
        return []
    with AUDIT_FILE.open("rb") as f:
        size = f.seek(0, 2)
        f.seek(max(0, size - tail_bytes))
        data = f.read().decode("utf-8", errors="ignore")
    lines = data.splitlines()[1:] if size > tail_bytes else data.splitlines()  # first line may be cut in half
    out = []
    for line in reversed(lines):
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if e.get("officer_id") == officer_id and e.get("officer_id_source") == OFFICER_ID_SOURCE:
            out.append({k: e.get(k) for k in ("verdict", "route", "input_type", "doc_hash", "officer_id", "timestamp")})
            if len(out) >= limit:
                break
    return out
