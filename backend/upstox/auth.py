"""
upstox/auth.py
==============
Upstox OAuth2 token manager.

Two ways to authenticate:
  1. OAuth flow  : GET /upstox/login → consent → callback → token saved
  2. Manual token: POST /upstox/save-token → paste token directly (simplest)

Manual token flow (recommended):
  - Go to account.upstox.com → Developer Apps → your app → copy Access Token
  - POST it to /upstox/save-token
  - Valid for 1 day — do this every morning before market opens

Redis keys:
  upstox:access_token  → str
  upstox:refresh_token → str
  upstox:token_expiry  → ISO-8601 datetime str
"""

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from redis_client import get_redis

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
UPSTOX_API_KEY: str = os.environ.get("UPSTOX_API_KEY", "")
UPSTOX_API_SECRET: str = os.environ.get("UPSTOX_API_SECRET", "")
UPSTOX_REDIRECT_URI: str = os.environ.get("UPSTOX_REDIRECT_URI", "")

BASE_URL = "https://api.upstox.com"
AUTH_URL = f"{BASE_URL}/v2/login/authorization/dialog"
TOKEN_URL = f"{BASE_URL}/v2/login/authorization/token"
REFRESH_URL = f"{BASE_URL}/v2/login/authorization/token"

REFRESH_BUFFER_MINUTES = 60

# Redis keys
_KEY_ACCESS  = "upstox:access_token"
_KEY_REFRESH = "upstox:refresh_token"
_KEY_EXPIRY  = "upstox:token_expiry"

# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------
router = APIRouter(prefix="/upstox", tags=["upstox-auth"])


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------
class TokenInput(BaseModel):
    access_token: str


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post("/save-token", summary="Manually save Upstox access token")
async def save_token(body: TokenInput) -> dict:
    """
    Simplest way to authenticate — no OAuth flow needed.

    Steps:
      1. Go to account.upstox.com → Developer Apps → your app
      2. Copy the Access Token shown there
      3. POST it here

    Do this every morning before market opens (token lasts 1 day).
    """
    if not body.access_token or len(body.access_token) < 10:
        raise HTTPException(status_code=400, detail="Invalid token — too short")

    expires_at = datetime.now(timezone.utc) + timedelta(hours=23)

    redis = await get_redis()
    pipe = redis.pipeline()
    pipe.set(_KEY_ACCESS, body.access_token, ex=82800)  # 23h TTL
    pipe.set(_KEY_EXPIRY, expires_at.isoformat())
    await pipe.execute()

    logger.info("Access token manually saved, expires at %s", expires_at.isoformat())
    return {
        "status": "ok",
        "message": "Token saved successfully. Valid until tomorrow morning.",
        "expires_at": expires_at.isoformat(),
    }


@router.get("/status", summary="Check current token status")
async def token_status() -> dict:
    """Returns whether a valid token is currently stored in Redis."""
    redis = await get_redis()
    access_token = await redis.get(_KEY_ACCESS)
    expiry_str   = await redis.get(_KEY_EXPIRY)

    if not access_token:
        return {
            "authenticated": False,
            "message": "No token found. POST to /upstox/save-token to authenticate.",
        }

    expiry = datetime.fromisoformat(expiry_str) if expiry_str else None
    now    = datetime.now(timezone.utc)
    minutes_left = int((expiry - now).total_seconds() / 60) if expiry else 0

    return {
        "authenticated": True,
        "expires_at": expiry_str,
        "minutes_remaining": minutes_left,
        "needs_refresh": minutes_left < REFRESH_BUFFER_MINUTES,
        "token_preview": access_token[:20] + "..." if access_token else None,
    }


@router.delete("/logout", summary="Remove stored tokens from Redis")
async def upstox_logout() -> dict:
    """Clears stored tokens. You will need to re-authenticate."""
    redis = await get_redis()
    await redis.delete(_KEY_ACCESS, _KEY_REFRESH, _KEY_EXPIRY)
    logger.info("Upstox tokens cleared from Redis")
    return {"status": "ok", "message": "Tokens cleared"}


@router.get("/login", summary="Redirect to Upstox OAuth2 consent page (alternative)")
async def upstox_login() -> RedirectResponse:
    """
    Alternative OAuth2 flow. Visit this URL in a browser.
    After consent Upstox redirects to REDIRECT_URI?code=...
    Simpler option: use POST /upstox/save-token instead.
    """
    if not UPSTOX_API_KEY:
        raise HTTPException(status_code=500, detail="UPSTOX_API_KEY not configured")

    params = {
        "response_type": "code",
        "client_id": UPSTOX_API_KEY,
        "redirect_uri": UPSTOX_REDIRECT_URI,
    }
    consent_url = f"{AUTH_URL}?{urlencode(params)}"
    logger.info("Redirecting to Upstox consent page")
    return RedirectResponse(url=consent_url)


@router.get("/callback", summary="Exchange auth code for tokens (OAuth2 callback)")
async def upstox_callback(request: Request):
    """
    Upstox redirects here after OAuth2 consent.
    Exchanges auth-code for access token and stores in Redis.
    """
    frontend_url = os.environ.get("FRONTEND_URL", "http://localhost:3000")
    code:  Optional[str] = request.query_params.get("code")
    error: Optional[str] = request.query_params.get("error")

    if error:
        logger.error("Upstox OAuth error: %s", error)
        return RedirectResponse(url=f"{frontend_url}/auth/callback?error={error}")

    if not code:
        return RedirectResponse(url=f"{frontend_url}/auth/callback?error=missing_code")

    try:
        token_data = await _exchange_code(code)
        await _store_tokens(token_data)
        logger.info("OAuth token obtained successfully")
        return RedirectResponse(url=f"{frontend_url}/auth/callback?success=1")
    except Exception as e:
        logger.error("Token exchange error: %s", e)
        return RedirectResponse(url=f"{frontend_url}/auth/callback?error=token_exchange_failed")


# ---------------------------------------------------------------------------
# Core helper — used by every module that needs a token
# ---------------------------------------------------------------------------

async def get_access_token() -> str:
    """
    Returns a valid Upstox access token from Redis.

    Raises:
        UpstoxAuthError: when no token exists — call POST /upstox/save-token
    """
    redis = await get_redis()

    access_token: Optional[str] = await redis.get(_KEY_ACCESS)
    expiry_str:   Optional[str] = await redis.get(_KEY_EXPIRY)

    if not access_token:
        raise UpstoxAuthError(
            "No Upstox token found. "
            "POST your token to /upstox/save-token to authenticate."
        )

    # Auto-refresh via OAuth refresh_token if near expiry
    if expiry_str:
        expiry = datetime.fromisoformat(expiry_str)
        now    = datetime.now(timezone.utc)
        minutes_left = (expiry - now).total_seconds() / 60

        if minutes_left < REFRESH_BUFFER_MINUTES:
            logger.info("Token expires in %.0f min — attempting refresh", minutes_left)
            try:
                access_token = await _refresh_access_token()
            except UpstoxAuthError:
                # Refresh failed — token still usable until it actually expires
                logger.warning("Refresh failed — using existing token")

    return access_token


async def get_auth_headers() -> dict:
    """Returns Authorization header dict required by Upstox API v2."""
    token = await get_access_token()
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "Api-Version": "2.0",
    }


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

async def _exchange_code(code: str) -> dict:
    """POST to Upstox token endpoint and return parsed token payload."""
    payload = {
        "code": code,
        "client_id": UPSTOX_API_KEY,
        "client_secret": UPSTOX_API_SECRET,
        "redirect_uri": UPSTOX_REDIRECT_URI,
        "grant_type": "authorization_code",
    }

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(TOKEN_URL, data=payload)

    if resp.status_code != 200:
        logger.error("Token exchange failed: %s %s", resp.status_code, resp.text)
        raise HTTPException(
            status_code=502,
            detail=f"Upstox token exchange failed: {resp.text}",
        )

    data = resp.json()
    expires_in: int = data.get("expires_in", 86400)
    data["expires_at"] = (
        datetime.now(timezone.utc) + timedelta(seconds=expires_in)
    ).isoformat()

    logger.info("OAuth token obtained, expires at %s", data["expires_at"])
    return data


async def _refresh_access_token() -> str:
    """
    Uses stored refresh_token to get a new access_token.
    Only works with OAuth flow tokens — not manually saved tokens.
    """
    redis = await get_redis()
    refresh_token: Optional[str] = await redis.get(_KEY_REFRESH)

    if not refresh_token:
        raise UpstoxAuthError("No refresh token — re-authenticate via /upstox/save-token")

    payload = {
        "refresh_token": refresh_token,
        "client_id": UPSTOX_API_KEY,
        "client_secret": UPSTOX_API_SECRET,
        "grant_type": "refresh_token",
    }

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(REFRESH_URL, data=payload)

    if resp.status_code != 200:
        logger.error("Token refresh failed: %s %s", resp.status_code, resp.text)
        await redis.delete(_KEY_ACCESS, _KEY_REFRESH, _KEY_EXPIRY)
        raise UpstoxAuthError("Token refresh failed — re-authenticate via /upstox/save-token")

    data = resp.json()
    expires_in: int = data.get("expires_in", 86400)
    data["expires_at"] = (
        datetime.now(timezone.utc) + timedelta(seconds=expires_in)
    ).isoformat()

    await _store_tokens(data)
    logger.info("Token refreshed, expires at %s", data["expires_at"])
    return data["access_token"]


async def _store_tokens(token_data: dict) -> None:
    """Persists access_token, refresh_token, expiry in Redis."""
    redis = await get_redis()

    access_token:  str           = token_data["access_token"]
    refresh_token: Optional[str] = token_data.get("refresh_token")
    expires_at:    str           = token_data["expires_at"]
    expires_in:    int           = token_data.get("expires_in", 86400)

    access_ttl = max(expires_in - 300, 300)

    pipe = redis.pipeline()
    pipe.set(_KEY_ACCESS, access_token, ex=access_ttl)
    pipe.set(_KEY_EXPIRY, expires_at)
    if refresh_token:
        pipe.set(_KEY_REFRESH, refresh_token)
    await pipe.execute()

    logger.debug("Tokens stored: ttl=%ds expiry=%s", access_ttl, expires_at)


# ---------------------------------------------------------------------------
# Custom exception
# ---------------------------------------------------------------------------

class UpstoxAuthError(Exception):
    """Raised when a valid Upstox access token cannot be obtained."""