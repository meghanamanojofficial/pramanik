"""Issuer service core: API-key auth, per-document-type registries, field comparison, audit.

The issuer receives the fields Pramanik extracted from a document and answers
found / status / per-field match. It does not hand its record back
(unless a registry explicitly sets "disclose_values": true).

Framework-free so it can be tested without FastAPI; main.py is a thin HTTP adapter.
"""
import hashlib
import hmac
import json
import re
import time
import unicodedata
from collections import defaultdict, deque
from pathlib import Path
from typing import Optional, Tuple


def hash_key(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _s(value) -> str:
    return "" if value is None else str(value)


def _records_as_list(data) -> list:
    """Accept [ {...} ], {"records": [ {...} ]} or {"INC-1": {...}}."""
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        if isinstance(data.get("records"), list):
            return data["records"]
        return [{"certificate_number": k, **v} for k, v in data.items() if isinstance(v, dict)]
    raise ValueError("Unrecognised registry file format")


# ---- field comparison, driven by the schema ---------------------------
def normalise(spec: dict, value) -> str:
    out = re.sub(r"\s+", " ", _s(value).strip())
    for op in spec.get("normalize", []):
        if op == "digits_only":
            out = re.sub(r"\D", "", out)
        else:
            raise ValueError(f"unknown normalize op: {op}")
    return out


def name_key(value) -> str:
    """Canonical form of a personal name: case, accents-as-composed, punctuation, spacing and
    word order are ignored. Anything else (a changed, added or missing letter) is a different name."""
    text = unicodedata.normalize("NFKC", _s(value)).casefold()
    text = re.sub(r"[^\w\s]", " ", text)
    return " ".join(sorted(text.split()))


def field_matches(spec: dict, document_value, record_value) -> bool:
    """Compare one field using the schema's `compare` rule.

    method "exact"  (default) -> equal after normalisation
    method "name"             -> equal after name_key(); no fuzziness, so "Ravi Kumar" != "Ravi Kumari"
    method "fuzzy"            -> rapidfuzz token_sort_ratio >= threshold. Loose: a one-letter edit can
                                 still score above 90, so do not use it for identity fields.
    """
    rule = spec.get("compare", {})
    method = rule.get("method", "exact")
    if method == "name":
        return name_key(document_value) == name_key(record_value)
    a, b = normalise(spec, document_value), normalise(spec, record_value)
    if rule.get("ignore_case"):
        a, b = a.lower(), b.lower()
    if method == "fuzzy":
        from rapidfuzz import fuzz
        return fuzz.token_sort_ratio(a, b) >= rule.get("threshold", 97)
    if method == "exact":
        return a == b
    raise ValueError(f"unknown compare method: {method}")


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
        self._cache = {}  # (records path, records mtime, schema mtime) -> index

    # ---- config -----------------------------------------------------
    def _config(self) -> dict:
        return json.loads(self.registries_path.read_text(encoding="utf-8"))

    def _schema_path(self, cfg) -> Path:
        return (self.registries_path.parent / cfg["schema_file"]).resolve()

    def _doc_spec(self, cfg, document_type: str) -> dict:
        types = json.loads(self._schema_path(cfg).read_text(encoding="utf-8"))["document_types"]
        return next(t for t in types if t["id"] == document_type)

    def _registry(self, cfg, document_type: str) -> Optional[dict]:
        return next((r for r in cfg["registries"] if r["document_type"] == document_type), None)

    def _index(self, cfg, reg: dict, spec: dict) -> dict:
        """{normalised key value: record}. Editing either JSON file takes effect live."""
        path = (self.registries_path.parent / reg["file"]).resolve()
        stamp = (path, path.stat().st_mtime, self._schema_path(cfg).stat().st_mtime)
        if stamp in self._cache:
            return self._cache[stamp]
        key_name = spec["key_field"]
        key_spec = next(f for f in spec["fields"] if f["name"] == key_name)
        records = _records_as_list(json.loads(path.read_text(encoding="utf-8")))
        index = {normalise(key_spec, r[key_name]): r for r in records if isinstance(r, dict) and key_name in r}
        self._cache[stamp] = index
        return index

    # ---- audit ------------------------------------------------------
    def _audit(self, key_id, issuer_id, outcome):
        """No certificate numbers, names or amounts are ever logged."""
        if not self.audit_path:
            return
        line = {"ts": int(time.time()), "key_id": key_id, "issuer_id": issuer_id, "outcome": outcome}
        with self.audit_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(line) + "\n")

    # ---- shared front door ------------------------------------------
    def _gate(self, api_key):
        key = self.keys.authenticate(api_key)
        if key is None:
            self._audit(None, None, "unauthorized")
            return None, (401, {"error": "invalid or missing API key"})
        if not self.limiter.allow(key["key_id"]):
            self._audit(key["key_id"], key["issuer_id"], "rate_limited")
            return None, (429, {"error": "rate limit exceeded"})
        return key, None

    # ---- POST /v1/verify --------------------------------------------
    def verify(self, api_key: Optional[str], document_type, fields) -> Tuple[int, dict]:
        key, refused = self._gate(api_key)
        if refused:
            return refused
        if not isinstance(document_type, str) or not isinstance(fields, dict):
            return 400, {"error": "document_type and fields are required"}
        try:
            cfg = self._config()
            reg = self._registry(cfg, document_type)
            if reg is None:
                self._audit(key["key_id"], key["issuer_id"], "no_registry")
                return 404, {"error": "not found"}
            if reg["issuer_id"] != key["issuer_id"]:
                self._audit(key["key_id"], key["issuer_id"], "forbidden")
                return 403, {"error": "key is not authorised for this issuer"}
            spec = self._doc_spec(cfg, document_type)
            index = self._index(cfg, reg, spec)
            key_spec = next(f for f in spec["fields"] if f["name"] == spec["key_field"])
            record = index.get(normalise(key_spec, fields.get(spec["key_field"])))
            if record is None:
                self._audit(key["key_id"], reg["issuer_id"], "not_found")
                return 200, {"issuer_id": reg["issuer_id"], "found": False}
            matches = {f["name"]: field_matches(f, fields.get(f["name"]), record.get(f["name"]))
                       for f in spec["fields"]}
            body = {"issuer_id": reg["issuer_id"], "found": True,
                    "status": _s(record.get("status")), "matches": matches}
            if reg.get("disclose_values"):
                body["values"] = {f["name"]: record.get(f["name"]) for f in spec["fields"]}
        except (OSError, ValueError, KeyError, StopIteration, ImportError):
            self._audit(key["key_id"], key["issuer_id"], "registry_error")
            return 503, {"error": "registry unavailable"}
        self._audit(key["key_id"], reg["issuer_id"], "found")
        return 200, body

    # ---- GET /v1/stats ----------------------------------------------
    def stats(self, api_key: Optional[str]) -> Tuple[int, dict]:
        key, refused = self._gate(api_key)
        if refused:
            return refused
        try:
            cfg = self._config()
            total = 0
            for reg in cfg["registries"]:
                if reg["issuer_id"] == key["issuer_id"]:
                    total += len(self._index(cfg, reg, self._doc_spec(cfg, reg["document_type"])))
        except (OSError, ValueError, KeyError, StopIteration):
            return 503, {"error": "registry unavailable"}
        return 200, {"records_loaded": total}
