"""
upstox/historical.py
====================
Fetches daily OHLCV candles from Upstox API v2.

Endpoint:
  GET /v2/historical-candle/{instrument_key}/{interval}/{to_date}/{from_date}

Interval used: "day"

Redis cache:
  Key   : upstox:ohlcv:{instrument_key}:{date}
  TTL   : 3600 s (1 hour) — refreshed each call during market hours
          After 6 PM IST (market closed + EOD data settled) TTL = 86400 s

Returns a list of OHLCVCandle named-tuples sorted oldest → newest.
Downstream strategy code uses pandas DataFrames built from these.
"""

import logging
import os
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Optional
import json

import httpx
import pandas as pd

from redis_client import get_redis
from upstox.auth import get_auth_headers

logger = logging.getLogger(__name__)

BASE_URL = "https://api.upstox.com"

# How many calendar days back to fetch (≈ 1 year of trading data)
LOOKBACK_DAYS: int = int(os.getenv("OHLCV_LOOKBACK_DAYS", "400"))

# Redis TTL (seconds)
_CACHE_TTL_INTRADAY = 3600     # 1 h during market hours
_CACHE_TTL_EOD = 86400         # 24 h after market close

# IST offset
_IST = timezone(timedelta(hours=5, minutes=30))


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class OHLCVCandle:
    date: date
    open: float
    high: float
    low: float
    close: float
    volume: int
    oi: int  # open interest (0 for equities)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def fetch_daily_candles(
    instrument_key: str,
    days: int = LOOKBACK_DAYS,
    use_cache: bool = True,
) -> list[OHLCVCandle]:
    """
    Fetch daily OHLCV candles for an instrument.

    Args:
        instrument_key: Upstox key e.g. "NSE_EQ|INE002A01018"
        days          : how many calendar days back to fetch
        use_cache     : if False, skip Redis and always hit Upstox API

    Returns:
        List of OHLCVCandle sorted oldest → newest (ready for pandas)

    Raises:
        httpx.HTTPError on network failure
        RuntimeError on unexpected Upstox response
    """
    today = datetime.now(_IST).date()
    from_date = today - timedelta(days=days)

    if use_cache:
        cached = await _get_from_cache(instrument_key, today)
        if cached is not None:
            return cached

    candles = await _fetch_from_upstox(instrument_key, from_date, today)

    if use_cache:
        await _store_in_cache(instrument_key, today, candles)

    return candles


async def fetch_daily_candles_df(
    instrument_key: str,
    days: int = LOOKBACK_DAYS,
    use_cache: bool = True,
) -> pd.DataFrame:
    """
    Same as fetch_daily_candles but returns a pandas DataFrame.

    Columns: date, open, high, low, close, volume, oi
    Index  : RangeIndex (not date — strategy code uses positional indexing)
    Sorted : oldest row first (index 0 = oldest, index -1 = today)
    """
    candles = await fetch_daily_candles(instrument_key, days, use_cache)
    if not candles:
        return pd.DataFrame(
            columns=["date", "open", "high", "low", "close", "volume", "oi"]
        )

    df = pd.DataFrame([
        {
            "date": c.date,
            "open": c.open,
            "high": c.high,
            "low": c.low,
            "close": c.close,
            "volume": c.volume,
            "oi": c.oi,
        }
        for c in candles
    ])
    df = df.sort_values("date").reset_index(drop=True)
    return df


async def fetch_bulk_candles(
    instrument_keys: list[str],
    days: int = LOOKBACK_DAYS,
) -> dict[str, list[OHLCVCandle]]:
    """
    Fetch candles for multiple instruments concurrently.
    Returns dict {instrument_key: [OHLCVCandle, ...]}.
    Instruments that fail are logged and mapped to empty list.
    """
    import asyncio

    async def safe_fetch(key: str) -> tuple[str, list[OHLCVCandle]]:
        try:
            candles = await fetch_daily_candles(key, days)
            return key, candles
        except Exception as exc:
            logger.error("Failed to fetch %s: %s", key, exc)
            return key, []

    tasks = [safe_fetch(k) for k in instrument_keys]
    results = await asyncio.gather(*tasks)
    return dict(results)


# ---------------------------------------------------------------------------
# Upstox API call
# ---------------------------------------------------------------------------

async def _fetch_from_upstox(
    instrument_key: str,
    from_date: date,
    to_date: date,
) -> list[OHLCVCandle]:
    """Call Upstox v2 historical-candle endpoint and parse response."""
    # Upstox expects instrument_key URL-encoded (pipe → %7C handled by httpx)
    # Endpoint: /v2/historical-candle/{instrument_key}/day/{to_date}/{from_date}
    from_str = from_date.strftime("%Y-%m-%d")
    to_str = to_date.strftime("%Y-%m-%d")

    url = (
        f"{BASE_URL}/v2/historical-candle"
        f"/{instrument_key}"
        f"/day"
        f"/{to_str}"
        f"/{from_str}"
    )

    headers = await get_auth_headers()

    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.get(url, headers=headers)

    if resp.status_code == 401:
        raise RuntimeError(f"Upstox auth error fetching {instrument_key}: token invalid")

    if resp.status_code == 429:
        raise RuntimeError(f"Upstox rate limit hit fetching {instrument_key}")

    if resp.status_code != 200:
        logger.error(
            "Upstox historical API error %s for %s: %s",
            resp.status_code, instrument_key, resp.text[:200],
        )
        raise RuntimeError(
            f"Upstox historical API returned {resp.status_code} for {instrument_key}"
        )

    body = resp.json()
    status = body.get("status", "")

    if status != "success":
        logger.warning(
            "Upstox returned non-success for %s: %s", instrument_key, body
        )
        return []

    raw_candles: list = body.get("data", {}).get("candles", [])

    if not raw_candles:
        logger.warning("No candles returned for %s", instrument_key)
        return []

    candles = _parse_candles(raw_candles)
    logger.debug(
        "Fetched %d candles for %s (%s → %s)",
        len(candles), instrument_key, from_str, to_str,
    )
    return candles


def _parse_candles(raw: list) -> list[OHLCVCandle]:
    """
    Parse Upstox candle list.

    Each element is:
      [timestamp, open, high, low, close, volume, open_interest]
      timestamp format: "2024-01-15T00:00:00+05:30"
    """
    candles = []
    for row in raw:
        try:
            ts_str: str = row[0]
            # Parse ISO timestamp → extract date
            ts = datetime.fromisoformat(ts_str)
            candle_date = ts.date()

            candles.append(OHLCVCandle(
                date=candle_date,
                open=float(row[1]),
                high=float(row[2]),
                low=float(row[3]),
                close=float(row[4]),
                volume=int(row[5]),
                oi=int(row[6]) if len(row) > 6 else 0,
            ))
        except (IndexError, ValueError, TypeError) as exc:
            logger.warning("Skipping malformed candle row %s: %s", row, exc)
            continue

    # Sort oldest → newest
    candles.sort(key=lambda c: c.date)
    return candles


# ---------------------------------------------------------------------------
# Redis cache helpers
# ---------------------------------------------------------------------------

def _cache_key(instrument_key: str, as_of: date) -> str:
    safe_key = instrument_key.replace("|", "_").replace("/", "_")
    return f"upstox:ohlcv:{safe_key}:{as_of.isoformat()}"


def _cache_ttl() -> int:
    """
    Return appropriate TTL based on current IST time.
    After 6 PM IST (market closed, EOD data settled) → 24h TTL.
    Otherwise → 1h TTL so intraday updates are visible.
    """
    now_ist = datetime.now(_IST)
    if now_ist.hour >= 18:
        return _CACHE_TTL_EOD
    return _CACHE_TTL_INTRADAY


async def _get_from_cache(
    instrument_key: str, as_of: date
) -> Optional[list[OHLCVCandle]]:
    redis = await get_redis()
    key = _cache_key(instrument_key, as_of)
    raw = await redis.get(key)  # str because decode_responses=True
    if raw is None:
        return None
    try:
        data = json.loads(raw)
        candles = [
            OHLCVCandle(
                date=date.fromisoformat(d["date"]),
                open=d["open"],
                high=d["high"],
                low=d["low"],
                close=d["close"],
                volume=d["volume"],
                oi=d["oi"],
            )
            for d in data
        ]
        logger.debug("Cache hit for %s (%d candles)", instrument_key, len(candles))
        return candles
    except (json.JSONDecodeError, KeyError, ValueError) as exc:
        logger.warning("Cache decode error for %s: %s — refetching", instrument_key, exc)
        return None


async def _store_in_cache(
    instrument_key: str,
    as_of: date,
    candles: list[OHLCVCandle],
) -> None:
    redis = await get_redis()
    key = _cache_key(instrument_key, as_of)
    ttl = _cache_ttl()
    data = [
        {
            "date": c.date.isoformat(),
            "open": c.open,
            "high": c.high,
            "low": c.low,
            "close": c.close,
            "volume": c.volume,
            "oi": c.oi,
        }
        for c in candles
    ]
    await redis.set(key, json.dumps(data), ex=ttl)
    logger.debug(
        "Cached %d candles for %s (TTL %ds)", len(candles), instrument_key, ttl
    )
