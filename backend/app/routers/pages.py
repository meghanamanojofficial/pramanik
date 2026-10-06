"""The web pages. Each page checks the session on the server before it is sent, so a signed-out visitor never
receives (or briefly sees) a protected page."""
from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, RedirectResponse, Response

from .. import security
from ..config import BACKEND_DIR

router = APIRouter()
FRONTEND = BACKEND_DIR.parent / "frontend"

PUBLIC = {"signin.html"}
NEEDS_LOGIN = {"creds.html"}
NEEDS_PROFILE = {"maindash.html", "analysing.html", "result.html"}


def _page(path, csp: str) -> FileResponse:
    return FileResponse(path, headers={"Cache-Control": "no-store", "Content-Security-Policy": csp})


def _go(where: str) -> Response:
    return RedirectResponse(where, status_code=303, headers={"Cache-Control": "no-store"})


@router.get("/", include_in_schema=False)
def index(request: Request):
    user = security.current_user(request)
    if user is None:
        return _go("/app/signin.html")
    return _go("/app/maindash.html" if user.profile_complete else "/app/creds.html")


@router.get("/app/{page}", include_in_schema=False)
def page(page: str, request: Request):
    if page not in PUBLIC | NEEDS_LOGIN | NEEDS_PROFILE:
        return Response(status_code=404)
    user = security.current_user(request)
    if page in PUBLIC:
        if user is not None:  # already signed in: skip the form
            return _go("/app/maindash.html" if user.profile_complete else "/app/creds.html")
    elif user is None:
        return _go("/app/signin.html")
    elif page in NEEDS_PROFILE and not user.profile_complete:
        return _go("/app/creds.html")
    return _page(FRONTEND / page, security.CSP_APP)


@router.get("/classic", include_in_schema=False)
def classic(request: Request):
    """The plain single-page view, kept as a fallback."""
    user = security.current_user(request)
    if user is None or not user.profile_complete:
        return _go("/app/signin.html")
    return _page(BACKEND_DIR / "static" / "index.html", security.CSP_CLASSIC)
