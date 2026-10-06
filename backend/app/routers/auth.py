from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .. import config, security
from ..services import accounts, throttle

router = APIRouter(prefix="/api/auth")

LOGIN_WINDOW = 15 * 60


class Credentials(BaseModel):
    email: str = Field("", max_length=300)
    password: str = Field("", max_length=300)
    signup_code: str = Field("", max_length=200)


class Profile(BaseModel):
    full_name: str = Field("", max_length=300)
    phone: str = Field("", max_length=300)
    organisation: str = Field("", max_length=300)
    role: str = Field("Officer", max_length=40)
    officer_id: str = Field("", max_length=300)


def _fail(status: int, key: str, **values) -> JSONResponse:
    return JSONResponse(status_code=status, content={"detail": config.message(key, **values)})


def _start_session(request: Request, user: accounts.User) -> JSONResponse:
    response = JSONResponse({"user": user.public()})
    response.set_cookie(security.COOKIE_NAME, accounts.create_session(user.id), max_age=accounts.session_seconds(),
                        httponly=True, samesite="lax", secure=security.cookie_secure(request), path="/")
    return response


@router.get("/options")
def options():
    return {"signup": security.signup_mode(), "roles": list(accounts.ROLES)}


@router.post("/signup")
def signup(body: Credentials, request: Request):
    mode, ip = security.signup_mode(), security.client_ip(request)
    if mode == "closed":
        return _fail(403, "auth_signup_closed")
    if throttle.blocked(f"signup:{ip}", 10, 3600):
        return _fail(429, "auth_too_many")
    throttle.record(f"signup:{ip}")
    if mode == "code" and not security.signup_code_ok(body.signup_code):
        return _fail(403, "auth_signup_code")
    try:
        user = accounts.create_user(body.email, body.password)
    except accounts.AccountError as e:
        return _fail(400 if e.key != "auth_email_taken" else 409, e.key, **e.values)
    return _start_session(request, user)


@router.post("/login")
def login(body: Credentials, request: Request):
    email, ip = accounts.normalise_email(body.email), security.client_ip(request)
    by_ip, by_email = f"login-ip:{ip}", f"login-email:{email}"
    if throttle.blocked(by_ip, 30, LOGIN_WINDOW) or throttle.blocked(by_email, 8, LOGIN_WINDOW):
        return _fail(429, "auth_too_many")
    user = accounts.authenticate(email, body.password)
    if user is None:
        throttle.record(by_ip)
        throttle.record(by_email)
        return _fail(401, "auth_bad_login")  # same answer for "no such account" and "wrong password"
    throttle.clear(by_email)
    return _start_session(request, user)


@router.post("/logout")
def logout(request: Request, response: Response):
    accounts.end_session(request.cookies.get(security.COOKIE_NAME))
    out = JSONResponse({"ok": True})
    out.delete_cookie(security.COOKIE_NAME, path="/")
    return out


@router.get("/me")
def me(request: Request):
    return {"user": security.require_user(request).public()}


@router.put("/profile")
def profile(body: Profile, request: Request):
    user = security.require_user(request)
    try:
        updated = accounts.update_profile(user.id, body.full_name, body.phone, body.organisation, body.role, body.officer_id)
    except accounts.AccountError as e:
        return _fail(409 if e.key == "auth_officer_id_taken" else 400, e.key, **e.values)
    return {"user": updated.public()}
