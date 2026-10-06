"""Who is asking, and how the browser is told to treat what we send."""
import hmac
import os
from typing import Optional

from fastapi import HTTPException, Request

from . import config
from .services import accounts

COOKIE_NAME = "pramanik_session"


def signup_mode() -> str:
    """open: anyone may create an account (demo). code: needs PRAMANIK_SIGNUP_CODE. closed: accounts are made
    by an administrator with `python backend/tools/create_user.py`."""
    config.load_env()
    if os.environ.get("PRAMANIK_SIGNUP", "").strip().lower() == "closed":
        return "closed"
    return "code" if os.environ.get("PRAMANIK_SIGNUP_CODE") else "open"


def signup_code_ok(given: str) -> bool:
    return hmac.compare_digest((given or "").encode(), os.environ.get("PRAMANIK_SIGNUP_CODE", "").encode())


def is_https(request: Request) -> bool:
    return request.url.scheme == "https" or request.headers.get("x-forwarded-proto", "").lower() == "https"


def cookie_secure(request: Request) -> bool:
    config.load_env()
    setting = os.environ.get("PRAMANIK_COOKIE_SECURE", "auto").strip().lower()
    return is_https(request) if setting == "auto" else setting in ("1", "true", "yes")


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def current_user(request: Request) -> Optional[accounts.User]:
    return accounts.user_for_session(request.cookies.get(COOKIE_NAME))


def require_user(request: Request) -> accounts.User:
    user = current_user(request)
    if user is None:
        raise HTTPException(status_code=401, detail=config.message("auth_login_required"))
    return user


def require_profile(request: Request) -> accounts.User:
    user = require_user(request)
    if not user.profile_complete:
        raise HTTPException(status_code=403, detail=config.message("auth_profile_required"))
    return user


# Pages carry no inline script, so scripts may only come from this site. Styles allow inline because the pages
# use style attributes. The plain fallback page (/classic) has an inline script of its own.
CSP_APP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; "
           "font-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'")
CSP_CLASSIC = CSP_APP.replace("script-src 'self'", "script-src 'self' 'unsafe-inline'")
