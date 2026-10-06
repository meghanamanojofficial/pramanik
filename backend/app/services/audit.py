"""Append-only audit log. One JSON line per request, with no content, names, fields or case IDs.

officer_id is typed into the form (there is no login yet), so every line records it as self-reported.
The log shows what was checked and when; it is not proof of who checked it."""
import json
import threading
from pathlib import Path

OFFICER_ID_SOURCE = "self_reported"
AUDIT_FILE = Path(__file__).resolve().parents[2] / "audit.log"
_lock = threading.Lock()


def write_audit(doc_hash: str, verdict: str, route: str, officer_id: str, timestamp: str) -> None:
    line = json.dumps({"doc_hash": doc_hash, "verdict": verdict, "route": route,
                       "officer_id": officer_id, "officer_id_source": OFFICER_ID_SOURCE,
                       "timestamp": timestamp}, separators=(",", ":"))
    with _lock, AUDIT_FILE.open("a", encoding="utf-8") as f:
        f.write(line + "\n")
