import os
import hmac
import hashlib
from typing import Optional
from fastapi import Request, HTTPException, status
from fastapi.responses import RedirectResponse

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

APP_PASSCODE = os.getenv("APP_PASSCODE", "apartment123")
SECRET_KEY = os.getenv("SECRET_KEY", "apartment-hub-secret-salt-2026")
COOKIE_NAME = "apartment_session"
COOKIE_MAX_AGE = 30 * 24 * 60 * 60  # 30 days in seconds

ALLOWED_USERS = ["Tamir", "Mikush"]
DEFAULT_USER = "Tamir"


def get_expected_token() -> str:
    """Computes a deterministic HMAC-SHA256 signature for the active passcode."""
    return hmac.new(
        SECRET_KEY.encode("utf-8"),
        APP_PASSCODE.strip().encode("utf-8"),
        hashlib.sha256
    ).hexdigest()


def verify_session_cookie(cookie_val: Optional[str]) -> bool:
    """Verifies that the provided session cookie matches the expected token."""
    if not cookie_val:
        return False
    expected = get_expected_token()
    return hmac.compare_digest(cookie_val.strip(), expected)


def verify_passcode(entered: str) -> bool:
    """Checks whether the entered passcode matches the configured APP_PASSCODE."""
    if not entered:
        return False
    return hmac.compare_digest(entered.strip(), APP_PASSCODE.strip())


def is_authenticated(request: Request) -> bool:
    """Helper to check if a FastAPI request contains a valid session cookie."""
    token = request.cookies.get(COOKIE_NAME)
    return verify_session_cookie(token)


async def require_auth_api(request: Request):
    """FastAPI dependency for API endpoints: returns 401 if not authenticated."""
    if not is_authenticated(request):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Apartment passcode required. Please log in."
        )


def get_active_profile(request: Request) -> str:
    """Reads profile identifier from header or query param, falling back to default."""
    header_user = request.headers.get("X-Apartment-User")
    if header_user in ALLOWED_USERS:
        return header_user
    return DEFAULT_USER
