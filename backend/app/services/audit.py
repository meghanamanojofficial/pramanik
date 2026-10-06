"""Append-only audit log. One JSON line per request, with no content, names, fields or case IDs."""
import json
import threading
from pathlib import Path

AUDIT_FILE = Path(__file__).resolve().parents[2] / "audit.log"
_lock = threading.Lock()


def write_audit(doc_hash: str, verdict: str, route: str, officer_id: str, timestamp: str) -> None:
    line = json.dumps({"doc_hash": doc_hash, "verdict": verdict, "route": route,
                       "officer_id": officer_id, "timestamp": timestamp}, separators=(",", ":"))
    with _lock, AUDIT_FILE.open("a", encoding="utf-8") as f:
        f.write(line + "\n")
