"""Issuer service core: API-key auth, registry routing, lookup, audit.

Framework-free on purpose so it can be tested without FastAPI.
main.py is a thin HTTP adapter around IssuerCore.lookup().
"""
import hashlib
import hmac
import json
import time
from collections import defaultdict, deque
from pathlib import Path
from typing import Optional, Tuple


def hash_key(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _records_as_list(data) -> list:
    """Accept [ {...} ], {"records": [ {...} ]} or {"INC-1": {...}}."""
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        if isinstance(data.get("records"), list):
            return data["records"]
        return [
            {"certificate_number": k, **v}
            for k, v in data.items()
            if isinstance(v, dict)
        ]
    raise ValueError("Unrecognised registry file format")


class KeyStore:
    """Stores only SHA-256 hashes of API keys, never the raw keys."""

    def __init__(self, path: Path):
        self.path = Path(path)

    def _load(self) -> list:
        if not self.path.exists():
            return []
        return json.loads(self.path.read_text(encoding="utf-8")).get("keys", [])

    def authenticate(self, raw_key: Optional[str]) -> Optional[dict]:
        if not raw_key:
            return None
        digest = hash_key(raw_key)
        match = None
        for k in self._load():  # no early exit: same work for every key
            if hmac.compare_digest(k["sha256"], digest) and not k.get("revoked"):
                match = k
        return match


class RateLimiter:
    def __init__(self, per_minute: int):
        self.per_minute = per_minute
        self.hits = defaultdict(deque)

    def allow(self, key_id: str) -> bool:
        now = time.monotonic()
        q = self.hits[key_id]
        while q and now - q[0] > 60:
            q.popleft()
        if len(q) >= self.per_minute:
            return False
        q.append(now)
        return True


class IssuerCore:
    def __init__(self, registries_path, keys_path, audit_path=None, rate_limit_per_minute=60):
        self.registries_path = Path(registries_path)
        self.keys = KeyStore(keys_path)
        self.audit_path = Path(audit_path) if audit_path else None
        self.limiter = RateLimiter(rate_limit_per_minute)
        self._cache = {}  # file path -> (mtime, {cert_number: record})

    # ---- registries -------------------------------------------------
    def _registries(self) -> list:
        cfg = json.loads(self.registries_path.read_text(encoding="utf-8"))
        return cfg["registries"]

    def _index(self, registry: dict) -> dict:
        path = (self.registries_path.parent / registry["file"]).resolve()
        mtime = path.stat().st_mtime
        cached = self._cache.get(path)
        if cached and cached[0] == mtime:  # editing the JSON takes effect live
            return cached[1]
        records = _records_as_list(json.loads(path.read_text(encoding="utf-8")))
        index = {r["certificate_number"]: r for r in records if "certificate_number" in r}
        self._cache[path] = (mtime, index)
        return index

    def _route(self, cert_number: str) -> Optional[dict]:
        best = None
        for reg in self._registries():
            if cert_number.upper().startswith(reg["prefix"].upper()):
                if best is None or len(reg["prefix"]) > len(best["prefix"]):
                    best = reg
        return best

    # ---- audit ------------------------------------------------------
    def _audit(self, key_id, issuer_id, outcome):
        """No certificate numbers, names or amounts are ever logged."""
        if not self.audit_path:
            return
        line = {"ts": int(time.time()), "key_id": key_id, "issuer_id": issuer_id, "outcome": outcome}
        with self.audit_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(line) + "\n")

    # ---- the one operation ------------------------------------------
    def lookup(self, api_key: Optional[str], cert_number: str) -> Tuple[int, dict]:
        key = self.keys.authenticate(api_key)
        if key is None:
            self._audit(None, None, "unauthorized")
            return 401, {"error": "invalid or missing API key"}
        if not self.limiter.allow(key["key_id"]):
            self._audit(key["key_id"], key["issuer_id"], "rate_limited")
            return 429, {"error": "rate limit exceeded"}
        reg = self._route(cert_number)
        if reg is None:
            self._audit(key["key_id"], key["issuer_id"], "no_registry")
            return 404, {"error": "not found"}  # same body as a missing record
        if reg["issuer_id"] != key["issuer_id"]:
            self._audit(key["key_id"], key["issuer_id"], "forbidden")
            return 403, {"error": "key is not authorised for this issuer"}
        record = self._index(reg).get(cert_number)
        if record is None:
            self._audit(key["key_id"], reg["issuer_id"], "not_found")
            return 404, {"error": "not found"}
        self._audit(key["key_id"], reg["issuer_id"], "found")
        return 200, {"issuer_id": reg["issuer_id"], "record": record}
