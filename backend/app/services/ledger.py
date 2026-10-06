"""Tamper-evident ledger of checked documents, used to spot one certificate being presented in many cases.

Privacy: it stores keyed fingerprints (HMAC-SHA256 with PRAMANIK_FINGERPRINT_KEY), never names, amounts,
numbers or case IDs, so a copy of the database alone reveals nothing and cannot be matched against guesses.
Integrity: each row carries the hash of the previous row, so removing or editing a row breaks the chain
(see verify_chain()). The chain is protected within one process; run a single backend worker.

Without PRAMANIK_FINGERPRINT_KEY the ledger is switched off (checks that need it are skipped and say so)
rather than falling back to a guessable default key.
"""
import hashlib
import hmac
import json
import os
import time
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from sqlalchemy import Column, Integer, String, Text, create_engine, func, select
from sqlalchemy.orm import Session, declarative_base

from .. import config
from . import doctypes

Base = declarative_base()
GENESIS = "0" * 64
_lock = threading.Lock()
_engine = None
_engine_url = None


class Entry(Base):
    __tablename__ = "ledger"
    id = Column(Integer, primary_key=True, autoincrement=True)
    created_at = Column(String(32), nullable=False)
    doc_type = Column(Text, nullable=False)
    input_type = Column(Text, nullable=False)
    content_fp = Column(String(64), nullable=False, index=True)
    case_fp = Column(String(64), nullable=False)
    stamp_hash = Column(String(32), nullable=True, index=True)
    verdict = Column(Text, nullable=False)
    prev_hash = Column(String(64), nullable=False)
    entry_hash = Column(String(64), nullable=False)


class IssuerCache(Base):
    """The issuer's last answer for one exact set of printed values (see services/issuer_cache.py)."""
    __tablename__ = "issuer_cache"
    content_fp = Column(String(64), primary_key=True)
    doc_type = Column(Text, nullable=False)
    status = Column(Text, nullable=False)
    matches = Column(Text, nullable=False)       # JSON {field: bool}; never the issuer's own values
    stored_at = Column(Integer, nullable=False)  # unix seconds
    expires_at = Column(Integer, nullable=False)
    mac = Column(String(64), nullable=False)


def _key() -> Optional[bytes]:
    config.load_env()
    k = os.environ.get("PRAMANIK_FINGERPRINT_KEY", "")
    return k.encode("utf-8") if k else None


def url() -> str:
    config.load_env()
    default = f"sqlite:///{(config.BACKEND_DIR / 'data' / 'pramanik.db').as_posix()}"
    return os.environ.get("DATABASE_URL", default)


def enabled() -> bool:
    return _key() is not None


def _get_engine():
    """The engine for the configured database. It is remembered only once its tables exist, so a failed
    first attempt (database down, driver missing) is retried next time instead of being treated as ready."""
    global _engine, _engine_url
    u = url()
    if _engine is not None and _engine_url == u:
        return _engine
    if u.startswith("sqlite:///"):
        Path(u[len("sqlite:///"):]).parent.mkdir(parents=True, exist_ok=True)
    # a database that does not answer must not make every request wait: give up after a few seconds
    args = {"connect_timeout": 3} if u.startswith("postgresql") else {}
    engine = create_engine(u, pool_pre_ping=True, connect_args=args)
    Base.metadata.create_all(engine)  # raises if the database cannot be reached
    _engine, _engine_url = engine, u
    return engine


def init() -> bool:
    """Create the database and tables now (called at startup so request handling never creates files)."""
    if not enabled():
        return False
    try:
        _get_engine()
        return True
    except Exception:
        return False


def _hmac(label: str, *parts: str) -> str:
    return hmac.new(_key(), "|".join((label, *parts)).encode("utf-8"), hashlib.sha256).hexdigest()


def content_fingerprint(doc_type: dict, fields: dict) -> str:
    """Fingerprint of everything the schema says identifies this certificate's content."""
    vals = [doctypes.normalise(f, fields.get(f["name"])) for f in doc_type["fields"]]
    return _hmac("content", doc_type["id"], *vals)


def case_fingerprint(case_id: str) -> str:
    return _hmac("case", case_id.strip())


def other_case_count(content_fp: str, case_fp: str) -> int:
    """How many *different* cases this same certificate content has been checked in before."""
    with Session(_get_engine()) as db:
        return db.scalar(select(func.count(func.distinct(Entry.case_fp)))
                         .where(Entry.content_fp == content_fp, Entry.case_fp != case_fp)) or 0


def stamp_hashes(exclude_content_fp: str, limit: int = 5000) -> list[tuple[str, str]]:
    """(stamp_hash, content_fp) of earlier entries that belong to *other* certificates."""
    with Session(_get_engine()) as db:
        rows = db.execute(select(Entry.stamp_hash, Entry.content_fp)
                          .where(Entry.stamp_hash.is_not(None), Entry.content_fp != exclude_content_fp)
                          .order_by(Entry.id.desc()).limit(limit)).all()
    return [(r[0], r[1]) for r in rows]


def _entry_hash(prev: str, e: dict) -> str:
    material = "|".join([prev, e["created_at"], e["doc_type"], e["input_type"], e["content_fp"], e["case_fp"],
                         e["stamp_hash"] or "", e["verdict"]])
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def record(doc_type: dict, fields: dict, case_id: str, input_type: str, verdict: str,
           stamp_hash: Optional[str] = None) -> Optional[str]:
    """Append an entry. Returns its hash, or None if the ledger is off or the write failed
    (a ledger problem must never change what the officer is told about the document)."""
    if not enabled():
        return None
    try:
        e = {"created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ"), "doc_type": doc_type["id"],
             "input_type": input_type, "content_fp": content_fingerprint(doc_type, fields),
             "case_fp": case_fingerprint(case_id), "stamp_hash": stamp_hash, "verdict": verdict}
        with _lock, Session(_get_engine()) as db:
            last = db.scalar(select(Entry.entry_hash).order_by(Entry.id.desc()).limit(1)) or GENESIS
            e["prev_hash"], e["entry_hash"] = last, _entry_hash(last, e)
            db.add(Entry(**e))
            db.commit()
        return e["entry_hash"]
    except Exception:
        return None


def verify_chain() -> tuple[bool, Optional[int]]:
    """(True, None) if every row links to the one before and hashes correctly, else (False, first bad id)."""
    prev = GENESIS
    with Session(_get_engine()) as db:
        for row in db.scalars(select(Entry).order_by(Entry.id)):
            e = {c.name: getattr(row, c.name) for c in Entry.__table__.columns}
            if row.prev_hash != prev or _entry_hash(prev, e) != row.entry_hash:
                return False, row.id
            prev = row.entry_hash
    return True, None


# ---- issuer-answer cache -------------------------------------------------------------------------
def _cache_mac(fp: str, doc_type: str, status: str, matches: str, stored_at: int, expires_at: int) -> str:
    return _hmac("cache", fp, doc_type, status, matches, str(stored_at), str(expires_at))


def cache_get(fp: str, now: Optional[int] = None) -> Optional[dict]:
    """A live, authentic entry or None. An entry whose MAC does not verify (someone edited the database)
    is ignored and removed rather than believed."""
    now = int(now if now is not None else time.time())
    try:
        with Session(_get_engine()) as db:
            row = db.get(IssuerCache, fp)
            if row is None:
                return None
            ok = hmac.compare_digest(row.mac, _cache_mac(fp, row.doc_type, row.status, row.matches,
                                                         row.stored_at, row.expires_at))
            if not ok or row.expires_at <= now:
                db.delete(row)
                db.commit()
                return None
            return {"status": row.status, "matches": json.loads(row.matches), "age_seconds": max(0, now - row.stored_at)}
    except Exception:
        return None


def cache_put(fp: str, doc_type: str, status: str, matches: dict, ttl_seconds: int, now: Optional[int] = None) -> None:
    now = int(now if now is not None else time.time())
    expires, body = now + int(ttl_seconds), json.dumps(matches, sort_keys=True)
    try:
        with _lock, Session(_get_engine()) as db:
            db.merge(IssuerCache(content_fp=fp, doc_type=doc_type, status=status, matches=body, stored_at=now,
                                 expires_at=expires, mac=_cache_mac(fp, doc_type, status, body, now, expires)))
            for old in db.scalars(select(IssuerCache).where(IssuerCache.expires_at <= now)):
                db.delete(old)  # housekeeping: expired rows are useless
            db.commit()
    except Exception:
        pass  # a cache problem only means the next check asks the issuer


def cache_drop(fp: str) -> None:
    try:
        with _lock, Session(_get_engine()) as db:
            row = db.get(IssuerCache, fp)
            if row is not None:
                db.delete(row)
                db.commit()
    except Exception:
        pass
