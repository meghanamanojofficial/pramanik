"""Create an account from the command line (for deployments with sign-up closed).

    python tools/create_user.py officer@example.gov.in --officer-id OFC-4921 --name "A. Officer" --org "Revenue Dept"

The password is asked for, never passed on the command line (it would stay in shell history).
"""
import argparse
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.services import accounts  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("email")
    ap.add_argument("--officer-id", required=True)
    ap.add_argument("--name", required=True)
    ap.add_argument("--org", default="")
    ap.add_argument("--phone", default="")
    ap.add_argument("--role", default="Officer", choices=accounts.ROLES)
    args = ap.parse_args()
    password = getpass.getpass("Password: ")
    if password != getpass.getpass("Repeat password: "):
        print("The passwords differ.")
        return 1
    accounts.init()
    try:
        user = accounts.create_user(args.email, password)
        accounts.update_profile(user.id, args.name, args.phone, args.org, args.role, args.officer_id)
    except accounts.AccountError as e:
        print(f"Could not create the account: {e.key} {e.values or ''}")
        return 1
    print(f"Created {user.email} with officer ID {args.officer_id}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
