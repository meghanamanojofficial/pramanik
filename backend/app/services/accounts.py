"""Officer accounts and login sessions.

Passwords: scrypt with a random salt per account (standard library; nothing to install). Sessions: a random
token in an HttpOnly cookie; only its SHA-256 is stored, so a copy of the database cannot be used to log in,
and logging out (or an expiry) really ends the session on the server.

Accounts live in the same database as the reuse ledger (DATABASE_URL), in their own tables.
"""
import hashlib
import hmac
import os
import re
import secrets
import time
from dataclasses import dataclass
from typing import Optional

from sqlalchemy import Column, Integer, String, Text, delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import config
from . import ledger

Base = ledger.Base

_SCRYPT = {"n": 2 ** 14, "r": 8, "p": 1}
_EMAIL = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,189}\.[^@\s]{2,}$")
MIN_PASSWORD, MAX_PASSWORD = 8, 128
ROLES = ("Citizen", "Officer", "Employer", "Institution")


class UserRow(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, autoincrement=True)
    email = Column(String(254), unique=True, nullable=False)
    pw_hash = Column(Text, nullable=False)
    full_name = Column(Text, nullable=False, default="")
    phone = Column(Text, nullable=False, default="")
    organisation = Column(Text, nullable=False, default="")
    role = Column(Text, nullable=False, default="Officer")
    officer_id = Column(String(64), unique=True, nullable=True)
    created_at = Column(Integer, nullable=False)


class SessionRow(Base):
    __tablename__ = "sessions"
    token_hash = Column(String(64), primary_key=True)
    user_id = Column(Integer, nullable=False, index=True)
    created_at = Column(Integer, nullable=False)
    expires_at = Column(Integer, nullable=False)


@dataclass
class User:
    id: int
    email: str
    full_name: str
    phone: str
    organisation: str
    role: str
    officer_id: Optional[str]

    @property
    def profile_complete(self) -> bool:
        return bool(self.full_name and self.officer_id)

    def public(self) -> dict:
        return {"email": self.email, "full_name": self.full_name, "phone": self.phone, "organisation": self.organisation,
                "role": self.role, "officer_id": self.officer_id or "", "profile_complete": self.profile_complete}


class AccountError(Exception):
    """An expected, user-fixable problem. `key` is a message key in config/ui.json."""
    def __init__(self, key: str, **values):
        super().__init__(key)
        self.key, self.values = key, values


def init() -> None:
    """Create the tables. Unlike the ledger this is required: without accounts nobody can sign in."""
    ledger._get_engine()


def _engine():
    return ledger._get_engine()


def session_seconds() -> int:
    config.load_env()
    return int(float(os.environ.get("PRAMANIK_SESSION_HOURS", "8")) * 3600)


# ---- passwords -------------------------------------------------------------------------------------
def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, dklen=32, maxmem=64 * 1024 * 1024, **_SCRYPT)
    return f"scrypt${_SCRYPT['n']}${_SCRYPT['r']}${_SCRYPT['p']}${salt.hex()}${digest.hex()}"


def check_password(password: str, stored: str) -> bool:
    try:
        _, n, r, p, salt, digest = stored.split("$")
        got = hashlib.scrypt(password.encode("utf-8"), salt=bytes.fromhex(salt), n=int(n), r=int(r), p=int(p),
                             dklen=len(digest) // 2, maxmem=64 * 1024 * 1024)
        return hmac.compare_digest(got.hex(), digest)
    except (ValueError, TypeError):
        return False


_DUMMY = None


def _spend_time_like_a_real_check(password: str) -> None:
    """Unknown e-mail: still do the scrypt work, so response time does not reveal which e-mails exist."""
    global _DUMMY
    if _DUMMY is None:
        _DUMMY = hash_password("dummy-password-for-timing")
    check_password(password, _DUMMY)


def normalise_email(email: str) -> str:
    return (email or "").strip().lower()


def validate_new_credentials(email: str, password: str) -> str:
    email = normalise_email(email)
    if len(email) > 254 or not _EMAIL.match(email):
        raise AccountError("auth_email_invalid")
    if not (MIN_PASSWORD <= len(password or "") <= MAX_PASSWORD):
        raise AccountError("auth_password_length", min=MIN_PASSWORD, max=MAX_PASSWORD)
    return email


# ---- users -------------------------------------------------------------------------------------
def _user(row: UserRow) -> User:
    return User(row.id, row.email, row.full_name, row.phone, row.organisation, row.role, row.officer_id)


def create_user(email: str, password: str) -> User:
    email = validate_new_credentials(email, password)
    row = UserRow(email=email, pw_hash=hash_password(password), created_at=int(time.time()))
    try:
        with Session(_engine()) as db:
            db.add(row)
            db.commit()
            return _user(row)
    except IntegrityError:
        raise AccountError("auth_email_taken")


def authenticate(email: str, password: str) -> Optional[User]:
    with Session(_engine()) as db:
        row = db.scalar(select(UserRow).where(UserRow.email == normalise_email(email)))
        if row is None:
            _spend_time_like_a_real_check(password or "")
            return None
        return _user(row) if check_password(password or "", row.pw_hash) else None


def update_profile(user_id: int, full_name: str, phone: str, organisation: str, role: str, officer_id: str) -> User:
    full_name, phone, organisation, officer_id = (v.strip() for v in (full_name, phone, organisation, officer_id))
    if not full_name or len(full_name) > 120:
        raise AccountError("auth_name_required")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]{1,62}", officer_id):
        raise AccountError("auth_officer_id_invalid")
    if len(phone) > 40 or len(organisation) > 120:
        raise AccountError("auth_field_too_long")
    if role not in ROLES:
        role = "Officer"
    try:
        with Session(_engine()) as db:
            row = db.get(UserRow, user_id)
            row.full_name, row.phone, row.organisation, row.role, row.officer_id = full_name, phone, organisation, role, officer_id
            db.commit()
            return _user(row)
    except IntegrityError:
        raise AccountError("auth_officer_id_taken")


# ---- sessions -------------------------------------------------------------------------------------
def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_session(user_id: int) -> str:
    token, now = secrets.token_urlsafe(32), int(time.time())
    with Session(_engine()) as db:
        db.execute(delete(SessionRow).where(SessionRow.expires_at <= now))  # housekeeping
        db.add(SessionRow(token_hash=_hash_token(token), user_id=user_id, created_at=now, expires_at=now + session_seconds()))
        db.commit()
    return token


def user_for_session(token: Optional[str]) -> Optional[User]:
    if not token:
        return None
    with Session(_engine()) as db:
        sess = db.get(SessionRow, _hash_token(token))
        if sess is None or sess.expires_at <= int(time.time()):
            return None
        row = db.get(UserRow, sess.user_id)
        return _user(row) if row else None


def end_session(token: Optional[str]) -> None:
    if token:
        with Session(_engine()) as db:
            db.execute(delete(SessionRow).where(SessionRow.token_hash == _hash_token(token)))
            db.commit()
