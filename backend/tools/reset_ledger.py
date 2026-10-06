"""Start the reuse ledger and issuer-answer cache from empty (for demos and tests).

    python tools/reset_ledger.py --yes

Why: the ledger remembers every certificate and the cases it was checked in. With a single sample certificate,
checking it under several different case IDs correctly raises "already presented in other cases" warnings; this
clears that history. Only the SQLite default is handled; for another database, clear its tables yourself.
Stop the backend first (Windows will not delete a file that is in use).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.services import ledger  # noqa: E402


def main() -> int:
    u = ledger.url()
    if not u.startswith("sqlite:///"):
        print(f"The ledger uses {u.split(':')[0]}, not SQLite. Clear its tables (ledger, issuer_cache) yourself.")
        return 1
    path = Path(u[len("sqlite:///"):])
    if "--yes" not in sys.argv:
        print(f"This deletes {path}. Run again with --yes to confirm.")
        return 1
    try:
        path.unlink()
        print(f"Deleted {path}. It is recreated, empty, the next time the backend starts.")
    except FileNotFoundError:
        print("Nothing to delete: the ledger is already empty.")
    except PermissionError:
        print("The file is in use. Stop the backend and try again.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
