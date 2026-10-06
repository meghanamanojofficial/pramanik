"""One-command key setup. Run from anywhere:

    python issuer_service/setup_keys.py            # create missing keys
    python issuer_service/setup_keys.py --rotate   # replace all keys

For every issuer in backend/config/issuers.json it
  1. generates a random API key (shown nowhere; written only to backend/.env),
  2. stores the key's SHA-256 hash in issuer_service/keys.json,
  3. creates an Ed25519 signing key for certificate QR codes (private half stays in
     issuer_service/signing_keys/, public half goes to backend/config/issuer_keys.json),
and adds PRAMANIK_FINGERPRINT_KEY (for the reuse ledger) to backend/.env.
None of these files is committed (see .gitignore).

    python issuer_service/setup_keys.py --new-signing-key   # add a new signing key; the old one is retired
                                                            # (certificates it signed still verify)
"""
import argparse
import json
import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from core import hash_key  # noqa: E402
import signing  # noqa: E402


def read_env(path: Path) -> dict:
    out = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip()
    return out


def write_env(path: Path, env: dict) -> None:
    path.write_text("".join(f"{k}={v}\n" for k, v in env.items()), encoding="utf-8")


def main(issuers_config=None, env_path=None, keys_path=None, rotate=False) -> None:
    issuers_config = issuers_config or ROOT / "backend" / "config" / "issuers.json"
    env_path = env_path or ROOT / "backend" / ".env"
    keys_path = keys_path or ROOT / "issuer_service" / "keys.json"

    issuers = json.loads(Path(issuers_config).read_text(encoding="utf-8"))["issuers"]
    env = read_env(env_path)
    keys = []
    if keys_path.exists() and not rotate:
        keys = json.loads(keys_path.read_text(encoding="utf-8")).get("keys", [])

    for issuer in issuers:
        var, iid = issuer["api_key_env"], issuer["issuer_id"]
        key_id = f"pramanik-{iid}"
        if not rotate and env.get(var) and any(k["key_id"] == key_id for k in keys):
            print(f"{iid}: key already set up (use --rotate to replace)")
            continue
        raw = "pk_" + secrets.token_urlsafe(32)
        env[var] = raw
        keys = [k for k in keys if k["key_id"] != key_id]
        keys.append({"key_id": key_id, "issuer_id": iid, "sha256": hash_key(raw)})
        print(f"{iid}: new key created")

    write_env(env_path, env)
    keys_path.write_text(json.dumps({"keys": keys}, indent=2), encoding="utf-8")
    print(f"Wrote {env_path} and {keys_path}")


FINGERPRINT_VAR = "PRAMANIK_FINGERPRINT_KEY"


def setup_signing(issuers_config=None, signing_dir=None, public_keys=None, new_key=False) -> None:
    """One signing key per issuer (created if missing; with new_key=True a fresh one replaces the active one)."""
    issuers_config = Path(issuers_config or ROOT / "backend" / "config" / "issuers.json")
    signing_dir = Path(signing_dir or signing.SIGNING_DIR)
    public_keys = Path(public_keys or signing.PUBLIC_KEYS)
    for issuer in json.loads(issuers_config.read_text(encoding="utf-8"))["issuers"]:
        iid = issuer["issuer_id"]
        if not new_key and signing.active_kid(iid, public_keys) and (
                signing_dir / f"{signing.active_kid(iid, public_keys)}.key").exists():
            print(f"{iid}: signing key already set up (use --new-signing-key to add a new one)")
            continue
        print(f"{iid}: signing key {signing.generate_key(iid, signing_dir, public_keys)} created")


def setup_fingerprint_key(env_path=None) -> None:
    """The secret that keys the reuse ledger's fingerprints. Created once; changing it forgets history."""
    env_path = Path(env_path or ROOT / "backend" / ".env")
    env = read_env(env_path)
    if env.get(FINGERPRINT_VAR):
        return
    env[FINGERPRINT_VAR] = secrets.token_hex(32)
    write_env(env_path, env)
    print(f"Added {FINGERPRINT_VAR} to {env_path}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--rotate", action="store_true", help="replace the issuer API keys")
    ap.add_argument("--new-signing-key", action="store_true", help="add a new QR signing key (old one retired)")
    args = ap.parse_args()
    main(rotate=args.rotate)
    setup_signing(new_key=args.new_signing_key)
    setup_fingerprint_key()
