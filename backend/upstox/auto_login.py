"""
upstox/auto_login.py
====================
Automatic daily Upstox login using upstox-totp package.

Requires env vars:
  UPSTOX_MOBILE      = 10-digit mobile
  UPSTOX_PIN         = 6-digit Upstox PIN
  UPSTOX_TOTP_SECRET = alphanumeric TOTP secret
  UPSTOX_API_KEY     = from developer console
  UPSTOX_API_SECRET  = from developer console
  UPSTOX_REDIRECT_URI= from developer console
"""

import logging
import os

from upstox.auth import _store_tokens, UpstoxAuthError

logger = logging.getLogger(__name__)

UPSTOX_MOBILE:       str = os.environ.get("UPSTOX_MOBILE", "")
UPSTOX_PIN:          str = os.environ.get("UPSTOX_PIN", "")
UPSTOX_TOTP_SECRET:  str = os.environ.get("UPSTOX_TOTP_SECRET", "")
UPSTOX_API_KEY:      str = os.environ.get("UPSTOX_API_KEY", "")
UPSTOX_API_SECRET:   str = os.environ.get("UPSTOX_API_SECRET", "")
UPSTOX_REDIRECT_URI: str = os.environ.get("UPSTOX_REDIRECT_URI", "")


async def auto_login() -> bool:
    """
    Full automated login using upstox-totp package.
    Returns True on success, False on failure.
    """
    if not all([UPSTOX_MOBILE, UPSTOX_PIN, UPSTOX_TOTP_SECRET]):
        logger.error("Auto-login skipped: missing UPSTOX_MOBILE/PIN/TOTP_SECRET")
        return False

    logger.info("Starting TOTP auto-login for %s***", UPSTOX_MOBILE[:4])

    try:
        import asyncio
        # upstox_totp is sync — run in executor
        loop = asyncio.get_event_loop()
        token = await loop.run_in_executor(None, _sync_login)

        if not token:
            logger.error("Auto-login returned empty token")
            return False

        from datetime import datetime, timedelta, timezone
        expires_at = datetime.now(timezone.utc) + timedelta(hours=23)

        token_data = {
            "access_token": token,
            "expires_at": expires_at.isoformat(),
            "expires_in": 82800,
        }
        await _store_tokens(token_data)
        logger.info("Auto-login successful — token valid until %s", expires_at.isoformat())
        return True

    except Exception as e:
        logger.exception("Auto-login failed: %s", e)
        return False


def _sync_login() -> str:
    """Synchronous login using upstox_totp package."""
    try:
        from upstox_totp import UpstoxTOTP

        # Set env vars so upstox_totp picks them up
        os.environ["UPSTOX_API_KEY"]     = UPSTOX_API_KEY
        os.environ["UPSTOX_API_SECRET"]  = UPSTOX_API_SECRET
        os.environ["UPSTOX_REDIRECT_URI"]= UPSTOX_REDIRECT_URI
        os.environ["UPSTOX_MOBILE"]      = UPSTOX_MOBILE
        os.environ["UPSTOX_PIN"]         = UPSTOX_PIN
        os.environ["UPSTOX_TOTP_SECRET"] = UPSTOX_TOTP_SECRET

        upx = UpstoxTOTP()
        response = upx.app_token.get_access_token()

        if response.success and response.data:
            logger.info(
                "upstox_totp login success: user=%s broker=%s",
                getattr(response.data, "user_name", "?"),
                getattr(response.data, "broker", "?"),
            )
            return response.data.access_token
        else:
            logger.error("upstox_totp login failed: %s", response)
            return ""

    except ImportError:
        logger.error("upstox-totp not installed — add to requirements.txt")
        return ""
    except Exception as e:
        logger.exception("upstox_totp error: %s", e)
        return ""