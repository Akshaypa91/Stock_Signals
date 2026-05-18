"""
upstox/realtime.py
==================
Manages the Upstox v2 WebSocket market data feed.

Upstox WebSocket flow:
  1. Fetch a short-lived WebSocket auth URL via REST:
       GET /v2/feed/market-data-feed/authorize
       → { "data": { "authorizedRedirectUri": "wss://..." } }
  2. Connect to that WSS URL (no auth header needed — token embedded in URL)
  3. Send subscription message (protobuf → but Upstox also accepts JSON mode)
  4. Receive LTP ticks as protobuf binary frames

Since decoding protobuf requires the Upstox proto schema (not always publicly
available), we use the JSON subscription mode which returns clean JSON ticks.

Subscription message (JSON mode):
  {
    "guid": "unique-id",
    "method": "sub",
    "data": {
      "mode": "ltpc",           # ltpc = LTP + close + change
      "instrumentKeys": ["NSE_EQ|INE002A01018", ...]
    }
  }

Tick received:
  {
    "feeds": {
      "NSE_EQ|INE002A01018": {
        "ltpc": { "ltp": 2450.50, "ltt": "...", "ltq": 100, "cp": 2440.00 }
      }
    }
  }

This module:
  - Maintains a single persistent WS connection
  - Auto-reconnects with exponential back-off (max 60 s)
  - Allows callers to register/deregister subscriptions at runtime
  - Calls registered LTP callbacks so the LTP monitor can check SL/T1/T2
"""

import asyncio
import json
import logging
import uuid
from collections import defaultdict
from typing import Callable, Awaitable, Optional

import httpx
import websockets
from websockets.exceptions import ConnectionClosed, WebSocketException

from upstox.auth import get_auth_headers, UpstoxAuthError

logger = logging.getLogger(__name__)

BASE_URL = "https://api.upstox.com"
WS_AUTH_URL = f"{BASE_URL}/v3/feed/market-data-feed/authorize"

# Reconnect back-off: starts at 2 s, doubles up to 60 s
_BACKOFF_BASE = 2
_BACKOFF_MAX = 60

# Type alias for LTP callback
LTPCallback = Callable[[str, float], Awaitable[None]]


class UpstoxRealtimeFeed:
    """
    Singleton-style WebSocket feed manager.

    Usage:
        feed = UpstoxRealtimeFeed()
        await feed.start()                          # starts background task
        feed.subscribe("NSE_EQ|INE002A01018")
        feed.register_callback(my_async_fn)         # receives (instrument_key, ltp)
        await feed.stop()
    """

    def __init__(self) -> None:
        self._subscribed: set[str] = set()
        self._callbacks: list[LTPCallback] = []
        self._ws: Optional[websockets.WebSocketClientProtocol] = None
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._pending_subscribe: set[str] = set()   # queued while disconnected
        self._ltp_cache: dict[str, float] = {}       # latest LTP per key

    # ------------------------------------------------------------------
    # Public control
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start the background WebSocket listener task."""
        if self._task and not self._task.done():
            logger.debug("Realtime feed already running")
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop(), name="upstox-ws")
        logger.info("Upstox realtime feed started")

    async def stop(self) -> None:
        """Gracefully stop the WebSocket listener."""
        self._running = False
        if self._ws:
            await self._ws.close()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Upstox realtime feed stopped")

    def subscribe(self, instrument_key: str) -> None:
        """Add an instrument to the live feed subscription."""
        if instrument_key in self._subscribed:
            return
        self._subscribed.add(instrument_key)
        self._pending_subscribe.add(instrument_key)
        # If already connected, send subscription immediately
        if self._ws and not self._ws.closed:
            asyncio.create_task(self._send_subscribe({instrument_key}))
        logger.info("Subscribed: %s", instrument_key)

    def subscribe_many(self, instrument_keys: list[str]) -> None:
        """Bulk subscribe."""
        new_keys = set(instrument_keys) - self._subscribed
        if not new_keys:
            return
        self._subscribed.update(new_keys)
        self._pending_subscribe.update(new_keys)
        if self._ws and not self._ws.closed:
            asyncio.create_task(self._send_subscribe(new_keys))
        logger.info("Bulk subscribed %d instruments", len(new_keys))

    def unsubscribe(self, instrument_key: str) -> None:
        """Remove an instrument from the feed (best-effort)."""
        self._subscribed.discard(instrument_key)
        self._pending_subscribe.discard(instrument_key)
        self._ltp_cache.pop(instrument_key, None)
        if self._ws and not self._ws.closed:
            asyncio.create_task(self._send_unsubscribe({instrument_key}))

    def register_callback(self, fn: LTPCallback) -> None:
        """Register an async callback: async def cb(instrument_key: str, ltp: float)."""
        if fn not in self._callbacks:
            self._callbacks.append(fn)

    def unregister_callback(self, fn: LTPCallback) -> None:
        self._callbacks = [cb for cb in self._callbacks if cb is not fn]

    def get_ltp(self, instrument_key: str) -> Optional[float]:
        """Return last known LTP for a key, or None if not yet received."""
        return self._ltp_cache.get(instrument_key)

    def get_all_ltps(self) -> dict[str, float]:
        return dict(self._ltp_cache)

    @property
    def is_connected(self) -> bool:
        return self._ws is not None and not self._ws.closed

    # ------------------------------------------------------------------
    # Background connection loop
    # ------------------------------------------------------------------

    async def _run_loop(self) -> None:
        """Main reconnect loop with exponential back-off."""
        backoff = _BACKOFF_BASE

        while self._running:
            try:
                ws_url = await self._get_ws_url()
                await self._connect_and_listen(ws_url)
                backoff = _BACKOFF_BASE   # reset on clean disconnect
            except UpstoxAuthError as exc:
                logger.error("Auth error — cannot connect WS: %s", exc)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, _BACKOFF_MAX)
            except (ConnectionClosed, WebSocketException, OSError) as exc:
                if not self._running:
                    break
                logger.warning(
                    "WS disconnected (%s). Reconnecting in %ds…", exc, backoff
                )
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, _BACKOFF_MAX)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.exception("Unexpected WS error: %s", exc)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, _BACKOFF_MAX)

        logger.info("WS run loop exited")

    async def _get_ws_url(self) -> str:
        """Fetch the authorised WebSocket URL from Upstox REST API."""
        headers = await get_auth_headers()
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(WS_AUTH_URL, headers=headers)

        if resp.status_code != 200:
            raise RuntimeError(
                f"Failed to get WS auth URL: {resp.status_code} {resp.text[:100]}"
            )

        data = resp.json()
        ws_url: str = data["data"]["authorizedRedirectUri"]
        logger.debug("Got WS URL: %s…", ws_url[:60])
        return ws_url

    async def _connect_and_listen(self, ws_url: str) -> None:
        """Open WS connection, subscribe to all pending keys, then read ticks."""
        async with websockets.connect(
            ws_url,
            ping_interval=20,
            ping_timeout=30,
            close_timeout=10,
            max_size=2**22,   # 4 MB — large feed packets
        ) as ws:
            self._ws = ws
            logger.info("WS connected")

            # Subscribe to all known instruments
            if self._subscribed:
                await self._send_subscribe(self._subscribed)
                self._pending_subscribe.clear()

            # Listen for ticks
            async for message in ws:
                if not self._running:
                    break
                await self._handle_message(message)

        self._ws = None

    async def _handle_message(self, message: bytes | str) -> None:
        """Parse incoming WS message and dispatch LTP to callbacks."""
        try:
            if isinstance(message, bytes):
                # Upstox sends protobuf by default; if JSON mode is used we
                # get str. If bytes, attempt JSON decode first, else log and skip.
                text = message.decode("utf-8")
            else:
                text = message

            data = json.loads(text)

        except (UnicodeDecodeError, json.JSONDecodeError):
            # True protobuf binary — would need generated proto classes to decode.
            # Log a warning so operators know they need proto mode or JSON mode.
            logger.debug("Received binary (protobuf) frame — set mode=ltpc in sub")
            return

        feeds: dict = data.get("feeds", {})
        for instrument_key, feed_data in feeds.items():
            ltpc = feed_data.get("ltpc", {})
            ltp = ltpc.get("ltp")
            if ltp is None:
                continue

            ltp = float(ltp)
            self._ltp_cache[instrument_key] = ltp

            # Fire all callbacks
            for cb in self._callbacks:
                try:
                    await cb(instrument_key, ltp)
                except Exception as exc:
                    logger.error(
                        "LTP callback error for %s: %s", instrument_key, exc
                    )

    # ------------------------------------------------------------------
    # Subscription messages
    # ------------------------------------------------------------------

    async def _send_subscribe(self, keys: set[str]) -> None:
        if not self._ws or self._ws.closed or not keys:
            return
        msg = {
            "guid": str(uuid.uuid4()),
            "method": "sub",
            "data": {
                "mode": "ltpc",
                "instrumentKeys": list(keys),
            },
        }
        try:
            await self._ws.send(json.dumps(msg))
            logger.debug("Sent subscribe for %d keys", len(keys))
        except WebSocketException as exc:
            logger.warning("Failed to send subscribe: %s", exc)

    async def _send_unsubscribe(self, keys: set[str]) -> None:
        if not self._ws or self._ws.closed or not keys:
            return
        msg = {
            "guid": str(uuid.uuid4()),
            "method": "unsub",
            "data": {
                "mode": "ltpc",
                "instrumentKeys": list(keys),
            },
        }
        try:
            await self._ws.send(json.dumps(msg))
        except WebSocketException as exc:
            logger.warning("Failed to send unsubscribe: %s", exc)


# ---------------------------------------------------------------------------
# Module-level singleton — imported by main.py and the LTP monitor
# ---------------------------------------------------------------------------
feed = UpstoxRealtimeFeed()
