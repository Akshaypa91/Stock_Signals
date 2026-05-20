"""
upstox/auto_login.py
====================
Automatic daily Upstox login using TOTP (no manual browser needed).

How it works:
  1. Opens Upstox login page using httpx (no browser needed)
  2. Submits mobile + PIN
  3. Generates TOTP code from secret key
  4. Submits TOTP → gets auth_code
  5. Exchanges auth_code for access_token (reuses existing _exchange_code)
  6. Stores token in Redis

Setup:
  Add these to your .env:
    UPSTOX_MOBILE=9999999999        # your Upstox registered mobile
    UPSTOX_PIN=123456               # your 6-digit Upstox PIN
    UPSTOX_TOTP_SECRET=ABCD1234     # TOTP secret key (see instructions below)

How to get TOTP secret:
  1. Go to Upstox app → Profile → Security → 2FA
  2. Click "Can't scan QR code?" or "Enter key manually"
  3. Copy the alphanumeric secret key shown there
  4. Add it to .env as UPSTOX_TOTP_SECRET

Scheduled in main.py lifespan to run daily at 6:30 AM IST.
"""

import logging
import os
from datetime import datetime, timezone

import httpx
import pyotp

from upstox.auth import _exchange_code, _store_tokens, UpstoxAuthError

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
UPSTOX_MOBILE: str = os.environ.get("UPSTOX_MOBILE", "")
UPSTOX_PIN: str = os.environ.get("UPSTOX_PIN", "")
UPSTOX_TOTP_SECRET: str = os.environ.get("UPSTOX_TOTP_SECRET", "")

UPSTOX_API_KEY: str = os.environ.get("UPSTOX_API_KEY", "")
UPSTOX_REDIRECT_URI: str = os.environ.get("UPSTOX_REDIRECT_URI", "")

# Upstox login API endpoints (v2)
_BASE = "https://api.upstox.com"
_LOGIN_URL = f"{_BASE}/v2/login/authorization/dialog"
_VERIFY_MOBILE_URL = f"{_BASE}/v2/login/authorization/initiation"
_VERIFY_PIN_URL = f"{_BASE}/v2/login/authorization/mobile-pin"
_VERIFY_TOTP_URL = f"{_BASE}/v2/login/authorization/totp"


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------
async def auto_login() -> bool:
    """
    Perform full automated Upstox login using TOTP.

    Returns:
        True  — login successful, token stored in Redis
        False — login failed (check logs)
    """
    if not all([UPSTOX_MOBILE, UPSTOX_PIN, UPSTOX_TOTP_SECRET]):
        logger.error(
            "Auto-login skipped: UPSTOX_MOBILE, UPSTOX_PIN, or UPSTOX_TOTP_SECRET "
            "not set in environment. Add them to .env to enable auto-login."
        )
        return False

    logger.info("Starting Upstox auto-login for mobile: %s***", UPSTOX_MOBILE[:4])

    try:
        auth_code = await _get_auth_code()
        token_data = await _exchange_code(auth_code)
        await _store_tokens(token_data)
        logger.info(
            "Auto-login successful. Token valid until: %s",
            token_data.get("expires_at", "unknown"),
        )
        return True

    except UpstoxAuthError as e:
        logger.error("Auto-login failed (auth error): %s", e)
        return False
    except Exception as e:
        logger.exception("Auto-login failed (unexpected): %s", e)
        return False


# ---------------------------------------------------------------------------
# Step-by-step login flow
# ---------------------------------------------------------------------------
async def _get_auth_code() -> str:
    """
    Drives the Upstox login API step by step:
      mobile → PIN → TOTP → auth_code
    Returns the auth_code string.
    """
    async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:

        # ── Step 1: Initiate login with mobile number ──────────────────────
        logger.debug("Step 1: Sending mobile number")
        r1 = await client.post(
            _VERIFY_MOBILE_URL,
            json={
                "mobile": UPSTOX_MOBILE,
                "client_id": UPSTOX_API_KEY,
            },
            headers={"Accept": "application/json", "Content-Type": "application/json"},
        )
        _check(r1, "mobile initiation")

        # ── Step 2: Submit PIN ─────────────────────────────────────────────
        logger.debug("Step 2: Submitting PIN")
        r2 = await client.post(
            _VERIFY_PIN_URL,
            json={
                "mobile": UPSTOX_MOBILE,
                "client_id": UPSTOX_API_KEY,
                "pin": UPSTOX_PIN,
            },
            headers={"Accept": "application/json", "Content-Type": "application/json"},
        )
        _check(r2, "PIN verification")

        # ── Step 3: Generate TOTP and submit ──────────────────────────────
        totp_code = _generate_totp()
        logger.debug("Step 3: Submitting TOTP: %s", totp_code)

        r3 = await client.post(
            _VERIFY_TOTP_URL,
            json={
                "mobile": UPSTOX_MOBILE,
                "client_id": UPSTOX_API_KEY,
                "totp": totp_code,
                "redirect_uri": UPSTOX_REDIRECT_URI,
            },
            headers={"Accept": "application/json", "Content-Type": "application/json"},
        )
        _check(r3, "TOTP verification")

        # Response contains auth_code or a redirect URL with ?code=...
        data = r3.json()

        # Try direct field first
        if "code" in data:
            return data["code"]

        # Try redirect URL (some Upstox versions return redirect)
        redirect = data.get("redirect_url") or data.get("redirectUrl", "")
        if redirect and "code=" in redirect:
            auth_code = redirect.split("code=")[-1].split("&")[0]
            logger.debug("Got auth_code from redirect URL")
            return auth_code

        logger.error("Unexpected TOTP response: %s", data)
        raise UpstoxAuthError(f"Could not extract auth_code from TOTP response: {data}")


def _generate_totp() -> str:
    """Generate current TOTP code from secret key."""
    totp = pyotp.TOTP(UPSTOX_TOTP_SECRET)
    code = totp.now()
    logger.debug("Generated TOTP: %s (valid for ~%ds)", code, 30 - (int(datetime.now(timezone.utc).timestamp()) % 30))
    return code


def _check(response: httpx.Response, step: str) -> None:
    """Raise UpstoxAuthError if response is not 200."""
    if response.status_code not in (200, 201):
        raise UpstoxAuthError(
            f"Auto-login failed at '{step}': "
            f"HTTP {response.status_code} — {response.text[:300]}"
        )