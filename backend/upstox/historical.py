"""
upstox/historical.py
====================
Fetches daily OHLCV candles — Upstox primary, yfinance fallback.

Priority:
  1. Redis cache (fastest)
  2. Upstox API (if token available)
  3. yfinance fallback (if Upstox token missing/expired)

This means scanner works even without Upstox login.
"""

import json
import logging
import os
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Optional

import httpx
import pandas as pd

from redis_client import get_redis

logger = logging.getLogger(__name__)

BASE_URL = "https://api.upstox.com"
LOOKBACK_DAYS: int = int(os.getenv("OHLCV_LOOKBACK_DAYS", "400"))

_CACHE_TTL_INTRADAY = 3600
_CACHE_TTL_EOD = 86400
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
    oi: int


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def fetch_daily_candles(
    instrument_key: str,
    days: int = LOOKBACK_DAYS,
    use_cache: bool = True,
    symbol: Optional[str] = None,   # NSE symbol for yfinance fallback
) -> list[OHLCVCandle]:
    """
    Fetch daily OHLCV candles.
    Tries Upstox first, falls back to yfinance if token is missing.
    """
    today = datetime.now(_IST).date()

    if use_cache:
        cached = await _get_from_cache(instrument_key, today)
        if cached is not None:
            return cached

    # --- Try Upstox first ---
    try:
        from upstox.auth import get_auth_headers, UpstoxAuthError
        try:
            headers = await get_auth_headers()
            candles = await _fetch_from_upstox(instrument_key, today - timedelta(days=days), today, headers)
            if candles:
                if use_cache:
                    await _store_in_cache(instrument_key, today, candles)
                logger.debug("Upstox: fetched %d candles for %s", len(candles), instrument_key)
                return candles
        except UpstoxAuthError:
            logger.warning(
                "Upstox token not available for %s — falling back to yfinance", instrument_key
            )
    except Exception as e:
        logger.warning("Upstox fetch failed for %s: %s — trying yfinance", instrument_key, e)

    # --- Fallback: yfinance ---
    # Derive NSE symbol from instrument_key if not provided
    # instrument_key format: "NSE_EQ|INE002A01018" — we need the trading symbol
    # Use passed symbol if available
    if symbol:
        candles = await _fetch_from_yfinance(symbol, days)
        if candles:
            if use_cache:
                await _store_in_cache(instrument_key, today, candles)
            logger.info("yfinance fallback: fetched %d candles for %s", len(candles), symbol)
            return candles

    logger.error("Both Upstox and yfinance failed for %s", instrument_key)
    return []


async def fetch_daily_candles_df(
    instrument_key: str,
    days: int = LOOKBACK_DAYS,
    use_cache: bool = True,
    symbol: Optional[str] = None,
) -> pd.DataFrame:
    """Returns OHLCV as DataFrame sorted oldest→newest."""
    candles = await fetch_daily_candles(instrument_key, days, use_cache, symbol)
    if not candles:
        return pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume", "oi"])

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
    return df.sort_values("date").reset_index(drop=True)


# ---------------------------------------------------------------------------
# Upstox API fetch
# ---------------------------------------------------------------------------

async def _fetch_from_upstox(
    instrument_key: str,
    from_date: date,
    to_date: date,
    headers: dict,
) -> list[OHLCVCandle]:
    from_str = from_date.strftime("%Y-%m-%d")
    to_str = to_date.strftime("%Y-%m-%d")

    url = (
        f"{BASE_URL}/v2/historical-candle"
        f"/{instrument_key}/day/{to_str}/{from_str}"
    )

    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.get(url, headers=headers)

    if resp.status_code == 401:
        from upstox.auth import UpstoxAuthError
        raise UpstoxAuthError("Token invalid")

    if resp.status_code == 429:
        raise RuntimeError(f"Upstox rate limit hit for {instrument_key}")

    if resp.status_code != 200:
        raise RuntimeError(f"Upstox API {resp.status_code} for {instrument_key}: {resp.text[:200]}")

    body = resp.json()
    if body.get("status") != "success":
        return []

    raw_candles = body.get("data", {}).get("candles", [])
    return _parse_upstox_candles(raw_candles)


def _parse_upstox_candles(raw: list) -> list[OHLCVCandle]:
    candles = []
    for row in raw:
        try:
            ts = datetime.fromisoformat(row[0])
            candles.append(OHLCVCandle(
                date=ts.date(),
                open=float(row[1]),
                high=float(row[2]),
                low=float(row[3]),
                close=float(row[4]),
                volume=int(row[5]),
                oi=int(row[6]) if len(row) > 6 else 0,
            ))
        except (IndexError, ValueError, TypeError) as e:
            logger.warning("Skipping malformed candle: %s — %s", row, e)
    candles.sort(key=lambda c: c.date)
    return candles


# ---------------------------------------------------------------------------
# yfinance fallback
# ---------------------------------------------------------------------------

async def _fetch_from_yfinance(symbol: str, days: int) -> list[OHLCVCandle]:
    """
    Fetch OHLCV from Yahoo Finance as fallback.
    NSE symbols on Yahoo: RELIANCE.NS, INFY.NS, etc.
    Runs in executor since yfinance is sync.
    """
    import asyncio

    def _sync_fetch():
        try:
            import yfinance as yf
            ticker = f"{symbol.upper()}.NS"
            df = yf.download(
                ticker,
                period=f"{days}d",
                interval="1d",
                progress=False,
                auto_adjust=True,
                threads=False,
            )
            if df.empty:
                logger.warning("yfinance: no data for %s", ticker)
                return []

            candles = []
            for idx, row in df.iterrows():
                try:
                    candles.append(OHLCVCandle(
                        date=idx.date() if hasattr(idx, 'date') else idx,
                        open=float(row["Open"]),
                        high=float(row["High"]),
                        low=float(row["Low"]),
                        close=float(row["Close"]),
                        volume=int(row["Volume"]),
                        oi=0,
                    ))
                except Exception:
                    continue
            candles.sort(key=lambda c: c.date)
            return candles
        except ImportError:
            logger.error("yfinance not installed — run: pip install yfinance")
            return []
        except Exception as e:
            logger.error("yfinance fetch failed for %s: %s", symbol, e)
            return []

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _sync_fetch)


# ---------------------------------------------------------------------------
# Redis cache helpers
# ---------------------------------------------------------------------------

def _cache_key(instrument_key: str, as_of: date) -> str:
    safe = instrument_key.replace("|", "_").replace("/", "_")
    return f"upstox:ohlcv:{safe}:{as_of.isoformat()}"


def _cache_ttl() -> int:
    now_ist = datetime.now(_IST)
    return _CACHE_TTL_EOD if now_ist.hour >= 18 else _CACHE_TTL_INTRADAY


async def _get_from_cache(instrument_key: str, as_of: date) -> Optional[list[OHLCVCandle]]:
    redis = await get_redis()
    raw = await redis.get(_cache_key(instrument_key, as_of))
    if raw is None:
        return None
    try:
        data = json.loads(raw)
        return [
            OHLCVCandle(
                date=date.fromisoformat(d["date"]),
                open=d["open"], high=d["high"],
                low=d["low"], close=d["close"],
                volume=d["volume"], oi=d["oi"],
            )
            for d in data
        ]
    except Exception as e:
        logger.warning("Cache decode error for %s: %s", instrument_key, e)
        return None


async def _store_in_cache(
    instrument_key: str, as_of: date, candles: list[OHLCVCandle]
) -> None:
    redis = await get_redis()
    data = [
        {
            "date": c.date.isoformat(),
            "open": c.open, "high": c.high,
            "low": c.low, "close": c.close,
            "volume": c.volume, "oi": c.oi,
        }
        for c in candles
    ]
    await redis.set(_cache_key(instrument_key, as_of), json.dumps(data), ex=_cache_ttl())