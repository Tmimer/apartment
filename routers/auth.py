import os
from fastapi import APIRouter, Request, Response, Form, HTTPException, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel
from security import (
    verify_passcode,
    get_expected_token,
    COOKIE_NAME,
    COOKIE_MAX_AGE,
    is_authenticated,
    ALLOWED_USERS,
    DEFAULT_USER
)

auth_router = APIRouter(tags=["authentication"])


class LoginRequest(BaseModel):
    passcode: str


@auth_router.post("/api/auth/login")
def api_login(payload: LoginRequest, response: Response):
    """Validates passcode and sets persistent HTTP-only session cookie (30 days)."""
    if not verify_passcode(payload.passcode):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect passcode. Please try again."
        )

    token = get_expected_token()
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        max_age=COOKIE_MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=False,  # Can run on localhost without HTTPS, Render handles HTTPS proxying
        path="/"
    )
    return {
        "status": "ok",
        "message": "Authenticated successfully",
        "profiles": ALLOWED_USERS,
        "default_profile": DEFAULT_USER
    }


@auth_router.post("/api/auth/logout")
def api_logout(response: Response):
    """Clears the persistent session cookie."""
    response.delete_cookie(key=COOKIE_NAME, path="/")
    return {"status": "ok", "message": "Logged out"}


@auth_router.get("/api/auth/status")
def auth_status(request: Request):
    """Checks whether the client possesses a valid session cookie."""
    authed = is_authenticated(request)
    return {
        "authenticated": authed,
        "profiles": ALLOWED_USERS,
        "default_profile": DEFAULT_USER
    }


@auth_router.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    """Serves the clean mobile-friendly passcode login screen."""
    if is_authenticated(request):
        return RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)

    login_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "templates", "login.html")
    if os.path.exists(login_path):
        with open(login_path, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())

    # Fallback inline login page
    return HTMLResponse(content="""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Apartment Passcode</title></head>
<body style="background:#0b0f19;color:#fff;font-family:sans-serif;text-align:center;padding:50px;">
<h2>Apartment Hub</h2><p>Please enter passcode to continue.</p></body></html>""")
