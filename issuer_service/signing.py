"""Issuer-side signing of certificate QR codes (Ed25519). The private key never leaves this folder.

A real department would sign at the moment it prints a certificate and publish its public key. Here the
demo-document generator (backend/tools/make_test_pdfs.py) plays that role.

    token = base64url(payload JSON) + "." + base64url(signature over those exact payload bytes)
    payload = {"v": 1, "iss": <issuer_id>, "kid": <key id>, "t": <document type id>, "f": {<field>: <value>}}

Pramanik verifies with the public key only (backend/app/services/signing.py).
"""
import base64
import json
import os
from pathlib import Path
from typing import Optional

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519

ROOT = Path(__file__).resolve().parent.parent
SIGNING_DIR = ROOT / "issuer_service" / "signing_keys"          # private keys (never committed)
PUBLIC_KEYS = ROOT / "backend" / "config" / "issuer_keys.json"  # public keys (generated, not committed)


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode("ascii").rstrip("=")


def _read_public(path: Path) -> list:
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("keys", [])
    except (OSError, ValueError):
        return []


def active_kid(issuer_id: str, public_keys: Path = PUBLIC_KEYS) -> Optional[str]:
    return next((k["kid"] for k in reversed(_read_public(public_keys))
                 if k["issuer_id"] == issuer_id and k.get("status") == "active"), None)


def generate_key(issuer_id: str, signing_dir: Path = SIGNING_DIR, public_keys: Path = PUBLIC_KEYS) -> str:
    """Create a new signing key. Any earlier active key of this issuer becomes 'retired': it still verifies
    certificates already issued, but new certificates use the new key."""
    keys = _read_public(public_keys)
    n = 1 + sum(1 for k in keys if k["issuer_id"] == issuer_id)
    kid = f"{issuer_id}-v{n}"
    private = ed25519.Ed25519PrivateKey.generate()

    signing_dir.mkdir(parents=True, exist_ok=True)
    path = signing_dir / f"{kid}.key"
    path.write_bytes(private.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw,
                                           serialization.NoEncryption()))
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass  # not supported on every platform

    for k in keys:
        if k["issuer_id"] == issuer_id and k.get("status") == "active":
            k["status"] = "retired"
    keys.append({"issuer_id": issuer_id, "kid": kid, "status": "active",
                 "public_key": private.public_key().public_bytes(serialization.Encoding.Raw,
                                                                 serialization.PublicFormat.Raw).hex()})
    public_keys.parent.mkdir(parents=True, exist_ok=True)
    public_keys.write_text(json.dumps({"keys": keys}, indent=2), encoding="utf-8")
    return kid


def issue_token(issuer_id: str, document_type: str, fields: dict, kid: Optional[str] = None,
                signing_dir: Path = SIGNING_DIR, public_keys: Path = PUBLIC_KEYS) -> str:
    """The text to put in a certificate's QR code. Raises FileNotFoundError if there is no key yet."""
    kid = kid or active_kid(issuer_id, public_keys)
    if not kid:
        raise FileNotFoundError(f"no signing key for {issuer_id}; run issuer_service/setup_keys.py")
    private = ed25519.Ed25519PrivateKey.from_private_bytes((signing_dir / f"{kid}.key").read_bytes())
    payload = json.dumps({"v": 1, "iss": issuer_id, "kid": kid, "t": document_type, "f": fields},
                         sort_keys=True, separators=(",", ":")).encode("utf-8")
    return f"{_b64(payload)}.{_b64(private.sign(payload))}"
