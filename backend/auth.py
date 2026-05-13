"""
backend/auth.py — Google OAuth + JWT authentication

Flow:
  1. Frontend redirects user to Google OAuth consent screen
  2. Google redirects back to /auth/callback with a `code`
  3. Backend exchanges code for Google ID token via POST to token endpoint
  4. Backend verifies the ID token using google-auth library
  5. Backend issues its own short-lived session JWT (signed with APP_SECRET)
  6. Frontend stores the JWT in memory (not localStorage — XSS risk) and
     sends it as Authorization: Bearer <token> on every API request
  7. Backend's get_current_user() dependency verifies the JWT on each request

WHY our own JWT instead of passing Google's ID token directly:
  Google ID tokens expire in 1 hour and cannot be refreshed without a new
  OAuth flow. Our own JWT can have a configurable TTL (default 8h) and
  carries only the fields we need (user_id, email), keeping payloads small.

WHY HMAC-SHA256 instead of RSA:
  This is a monolithic app — the same backend issues and verifies tokens.
  Asymmetric signing (RSA) is needed when multiple services verify tokens
  independently. HMAC is simpler, faster, and sufficient here.

WHY PyJWT:
  Battle-tested, audited library. PyJWT 2.x explicitly rejects the `alg:none`
  attack and algorithm confusion by requiring the caller to specify accepted
  algorithms at decode time — the library never trusts the token header's alg
  field. We pass algorithms=["HS256"] so only HS256 tokens are accepted.

Required env vars (.env):
  GOOGLE_CLIENT_ID     — from Google Cloud Console
  GOOGLE_CLIENT_SECRET — from Google Cloud Console
  GOOGLE_REDIRECT_URI  — e.g. http://localhost:8000/auth/callback
  APP_SECRET           — random 32-byte hex string for JWT signing
"""

import os
import time
from typing import Optional

import httpx
import jwt
from fastapi import APIRouter, Depends, HTTPException, Query, Header
from fastapi.responses import RedirectResponse
from google.oauth2 import id_token as google_id_token
from google.auth.transport import requests as google_requests

# ---------------------------------------------------------------------------
# Config (loaded from env — set in .env and loaded by pipeline.py pattern)
# ---------------------------------------------------------------------------
GOOGLE_CLIENT_ID     = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
GOOGLE_REDIRECT_URI  = os.getenv("GOOGLE_REDIRECT_URI", "http://localhost:8000/auth/callback")
APP_SECRET           = os.getenv("APP_SECRET", "dev-secret-change-in-production-32x")
JWT_TTL_SECONDS      = int(os.getenv("JWT_TTL_SECONDS", "28800"))   # 8 hours

GOOGLE_AUTH_URL  = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"

# ---------------------------------------------------------------------------
# JWT — PyJWT 2.x
# algorithms=["HS256"] at decode time prevents algorithm confusion attacks:
# PyJWT will reject any token whose header claims a different algorithm,
# including the alg:none exploit present in older JWT libraries.
# ---------------------------------------------------------------------------

def create_jwt(user_id: str, email: str) -> str:
    return jwt.encode(
        {
            "sub":   user_id,
            "email": email,
            "iat":   int(time.time()),
            "exp":   int(time.time()) + JWT_TTL_SECONDS,
        },
        APP_SECRET,
        algorithm="HS256",
    )


def verify_jwt(token: str) -> dict:
    """Verify signature and expiry. Returns payload dict or raises HTTPException."""
    try:
        return jwt.decode(token, APP_SECRET, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError as e:
        raise HTTPException(status_code=401, detail=f"Invalid token: {e}")


# ---------------------------------------------------------------------------
# FastAPI dependency — used by every protected router
# ---------------------------------------------------------------------------

DEV_MODE = not GOOGLE_CLIENT_ID   # True when env vars not set

import logging as _logging
_logging.getLogger(__name__).warning(
    "AUTH INIT: DEV_MODE=%s GOOGLE_CLIENT_ID=%s",
    DEV_MODE, GOOGLE_CLIENT_ID[:10] + "..." if GOOGLE_CLIENT_ID else "EMPTY"
)


async def get_current_user(authorization: Optional[str] = Header(None)) -> str:
    """
    Returns user_id from verified JWT.
    In dev mode (no GOOGLE_CLIENT_ID set) returns a hardcoded dev user.
    """
    if DEV_MODE:
        return "dev-user-001"

    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Authorization header")

    token   = authorization.removeprefix("Bearer ")
    payload = verify_jwt(token)
    return payload["sub"]


# ---------------------------------------------------------------------------
# Auth router — /auth/login and /auth/callback
# ---------------------------------------------------------------------------

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/login")
def login():
    """Redirect the user to Google's OAuth consent screen."""
    if not GOOGLE_CLIENT_ID:
        raise HTTPException(
            status_code=501,
            detail="Google OAuth not configured. Set GOOGLE_CLIENT_ID in .env",
        )
    params = {
        "client_id":     GOOGLE_CLIENT_ID,
        "redirect_uri":  GOOGLE_REDIRECT_URI,
        "response_type": "code",
        "scope":         "openid email profile",
        "access_type":   "online",
    }
    query = "&".join(f"{k}={v}" for k, v in params.items())
    return RedirectResponse(url=f"{GOOGLE_AUTH_URL}?{query}")


@router.get("/google/callback")
async def oauth_callback(code: str = Query(...)):
    """
    Exchange Google auth code for ID token, verify it, issue our JWT.
    Frontend receives the JWT and stores it in memory.
    """
    if not GOOGLE_CLIENT_ID:
        raise HTTPException(status_code=501, detail="Google OAuth not configured")

    # Exchange code for tokens
    async with httpx.AsyncClient() as client:
        resp = await client.post(GOOGLE_TOKEN_URL, data={
            "code":          code,
            "client_id":     GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            "redirect_uri":  GOOGLE_REDIRECT_URI,
            "grant_type":    "authorization_code",
        })
    if resp.status_code != 200:
        raise HTTPException(status_code=400, detail="Failed to exchange code with Google")

    google_token = resp.json().get("id_token")
    if not google_token:
        raise HTTPException(status_code=400, detail="No id_token in Google response")

    # Verify ID token using google-auth
    try:
        id_info = google_id_token.verify_oauth2_token(
            google_token,
            google_requests.Request(),
            GOOGLE_CLIENT_ID,
        )
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Google token verification failed: {e}")

    user_id = id_info["sub"]
    email   = id_info.get("email", "")

    # Issue our own JWT
    jwt = create_jwt(user_id, email)

    # Redirect to frontend with token in query param — OAuthCallback component picks it up
    return RedirectResponse(url=f"/auth/callback?access_token={jwt}", status_code=302)


@router.get("/me")
async def me(user_id: str = Depends(get_current_user)):
    """Return the current user's ID — useful for frontend auth state check."""
    return {"user_id": user_id, "dev_mode": DEV_MODE}
