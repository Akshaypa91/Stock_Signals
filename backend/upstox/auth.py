"""
upstox/auth.py
==============
Upstox OAuth2 token manager.

Flow:
  1. User visits GET /upstox/login  → redirected to Upstox consent page
  2. Upstox redirects back to REDIRECT_URI with ?code=...
  3. GET /upstox/callback exchanges code → access_token + refresh_token
  4. Tokens stored in Redis (access_token TTL = 23 h, refresh kept indefinitely)
  5. Every API call uses get_access_token() which auto-refreshes when near expiry

Redis keys:
  upstox:access_token   → str
  upstox:refresh_token  → str
  upstox:token_expiry   → ISO-8601 datetime str
"""

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse

from redis_client import get_redis

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config (pulled from environment / .env via main.py lifespan)
# ---------------------------------------------------------------------------
UPSTOX_API_KEY: str = os.environ["UPSTOX_API_KEY"]
UPSTOX_API_SECRET: str = os.environ["UPSTOX_API_SECRET"]
UPSTOX_REDIRECT_URI: str = os.environ["UPSTOX_REDIRECT_URI"]

BASE_URL = "https://api.upstox.com"
AUTH_URL = f"{BASE_URL}/v2/login/authorization/dialog"
TOKEN_URL = f"{BASE_URL}/v2/login/authorization/token"
REFRESH_URL = f"{BASE_URL}/v2/login/authorization/token"   # same endpoint, different grant

# Refresh when less than this many minutes remain on the token
REFRESH_BUFFER_MINUTES = 60

# Redis keys
_KEY_ACCESS = "upstox:access_token"
_KEY_REFRESH = "upstox:refresh_token"
_KEY_EXPIRY = "upstox:token_expiry"

# ---------------------------------------------------------------------------
# FastAPI router  (mounted in main.py)
# ---------------------------------------------------------------------------
router = APIRouter(prefix="/upstox", tags=["upstox-auth"])


@router.get("/login", summary="Redirect to Upstox OAuth2 consent page")
async def upstox_login() -> RedirectResponse:
    """
    Start OAuth2 flow.  Visit this URL in a browser to authorise the app.
    After consent Upstox redirects to REDIRECT_URI?code=<auth_code>.
    """
    params = {
        "response_type": "code",
        "client_id": UPSTOX_API_KEY,
        "redirect_uri": UPSTOX_REDIRECT_URI,
    }
    consent_url = f"{AUTH_URL}?{urlencode(params)}"
    logger.info("Redirecting to Upstox consent page")
    return RedirectResponse(url=consent_url)


@router.get("/callback", summary="Exchange auth code for tokens")
async def upstox_callback(request: Request):
    """
    Upstox redirects here after user grants consent.
    Exchanges the auth-code for access + refresh tokens and stores them in Redis.
    Then redirects the popup to the frontend /auth/callback page.
    """
    frontend_url = os.environ.get("FRONTEND_URL", "http://localhost:3000")
    code: Optional[str] = request.query_params.get("code")
    error: Optional[str] = request.query_params.get("error")

    if error:
        logger.error("Upstox OAuth error: %s", error)
        return RedirectResponse(url=f"{frontend_url}/auth/callback?error={error}")

    if not code:
        return RedirectResponse(url=f"{frontend_url}/auth/callback?error=missing_code")

    try:
        token_data = await _exchange_code(code)
        await _store_tokens(token_data)
        logger.info("Upstox authenticated successfully")
        return RedirectResponse(url=f"{frontend_url}/auth/callback?success=1")
    except Exception as e:
        logger.error("Token exchange error: %s", e)
        return RedirectResponse(url=f"{frontend_url}/auth/callback?error=token_exchange_failed")


@router.get("/status", summary="Check current token status")
async def token_status() -> dict:
    """Returns whether a valid token is currently stored in Redis."""
    redis = await get_redis()
    access_token = await redis.get(_KEY_ACCESS)
    expiry_str = await redis.get(_KEY_EXPIRY)

    if not access_token:
        return {"authenticated": False, "message": "No access token found"}

    expiry = datetime.fromisoformat(expiry_str) if expiry_str else None
    now = datetime.now(timezone.utc)
    minutes_left = int((expiry - now).total_seconds() / 60) if expiry else 0

    return {
        "authenticated": True,
        "expires_at": expiry_str,
        "minutes_remaining": minutes_left,
        "needs_refresh": minutes_left < REFRESH_BUFFER_MINUTES,
    }


@router.delete("/logout", summary="Remove stored tokens from Redis")
async def upstox_logout() -> dict:
    """Clears stored tokens. User will need to re-authenticate."""
    redis = await get_redis()
    await redis.delete(_KEY_ACCESS, _KEY_REFRESH, _KEY_EXPIRY)
    logger.info("Upstox tokens cleared from Redis")
    return {"status": "ok", "message": "Tokens cleared"}


# ---------------------------------------------------------------------------
# Core helper — used by every other module that needs a token
# ---------------------------------------------------------------------------
async def get_access_token() -> str:
    """
    Returns a valid Upstox access token.

    Logic:
      1. Load token + expiry from Redis.
      2. If expiry is within REFRESH_BUFFER_MINUTES, silently refresh.
      3. If no token at all, raise AuthenticationError.

    Raises:
        UpstoxAuthError: when no token exists and user must re-authenticate.
    """
    redis = await get_redis()

    access_token: Optional[str] = await redis.get(_KEY_ACCESS)
    expiry_str: Optional[str] = await redis.get(_KEY_EXPIRY)

    if not access_token:
        raise UpstoxAuthError(
            "No Upstox access token found. "
            "Please visit /upstox/login to authenticate."
        )

    # Check if refresh needed
    if expiry_str:
        expiry = datetime.fromisoformat(expiry_str)
        now = datetime.now(timezone.utc)
        minutes_left = (expiry - now).total_seconds() / 60

        if minutes_left < REFRESH_BUFFER_MINUTES:
            logger.info(
                "Access token expires in %.0f min — refreshing now", minutes_left
            )
            access_token = await _refresh_access_token()

    return access_token


async def get_auth_headers() -> dict:
    """Returns the Authorization header dict required by Upstox API v2."""
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
        logger.error(
            "Token exchange failed: %s %s", resp.status_code, resp.text
        )
        raise HTTPException(
            status_code=502,
            detail=f"Upstox token exchange failed: {resp.text}",
        )

    data = resp.json()
    # Upstox returns expires_in (seconds from now)
    expires_in: int = data.get("expires_in", 86400)
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
    data["expires_at"] = expires_at.isoformat()

    logger.info("Token obtained, expires at %s", data["expires_at"])
    return data


async def _refresh_access_token() -> str:
    """
    Uses the stored refresh_token to obtain a new access_token.
    Stores the new token pair in Redis.
    Returns the new access_token string.
    """
    redis = await get_redis()
    refresh_token: Optional[str] = await redis.get(_KEY_REFRESH)

    if not refresh_token:
        raise UpstoxAuthError(
            "No refresh token available. Please re-authenticate via /upstox/login."
        )

    payload = {
        "refresh_token": refresh_token,
        "client_id": UPSTOX_API_KEY,
        "client_secret": UPSTOX_API_SECRET,
        "grant_type": "refresh_token",
    }

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(REFRESH_URL, data=payload)

    if resp.status_code != 200:
        logger.error(
            "Token refresh failed: %s %s", resp.status_code, resp.text
        )
        # Token may be fully expired — force re-auth
        await redis.delete(_KEY_ACCESS, _KEY_REFRESH, _KEY_EXPIRY)
        raise UpstoxAuthError(
            "Token refresh failed. Please re-authenticate via /upstox/login."
        )

    data = resp.json()
    expires_in: int = data.get("expires_in", 86400)
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
    data["expires_at"] = expires_at.isoformat()

    await _store_tokens(data)
    logger.info("Token refreshed successfully, expires at %s", data["expires_at"])
    return data["access_token"]


async def _store_tokens(token_data: dict) -> None:
    """
    Persists access_token, refresh_token, and expiry in Redis.
    access_token TTL is set to (expires_in - 300) seconds so Redis auto-evicts it
    slightly before Upstox does, keeping get_access_token() as the source of truth.
    """
    redis = await get_redis()

    access_token: str = token_data["access_token"]
    refresh_token: Optional[str] = token_data.get("refresh_token")
    expires_at: str = token_data["expires_at"]
    expires_in: int = token_data.get("expires_in", 86400)

    # TTL for Redis key: slightly shorter than actual token lifetime
    access_ttl = max(expires_in - 300, 300)

    pipe = redis.pipeline()
    pipe.set(_KEY_ACCESS, access_token, ex=access_ttl)
    pipe.set(_KEY_EXPIRY, expires_at)
    if refresh_token:
        # Refresh tokens don't expire on a fixed schedule; keep indefinitely
        pipe.set(_KEY_REFRESH, refresh_token)
    await pipe.execute()

    logger.debug(
        "Stored tokens: access_ttl=%ds, expiry=%s", access_ttl, expires_at
    )


# ---------------------------------------------------------------------------
# Custom exception
# ---------------------------------------------------------------------------
class UpstoxAuthError(Exception):
    """Raised when a valid Upstox access token cannot be obtained."""
