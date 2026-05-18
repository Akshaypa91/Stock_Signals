"""
upstox/instruments.py
=====================
Maps NSE ticker symbols → Upstox instrument_key (e.g. "NSE_EQ|INE002A01018").

Upstox publishes a master CSV at:
  https://assets.upstox.com/market-quote/instruments/exchange/NSE.csv.gz

This module downloads + caches that file in Redis (TTL 24h) and builds an
in-memory dict for fast lookup during the trading session.

Instrument CSV columns (relevant ones):
  instrument_key  tradingsymbol  name  exchange  instrument_type  isin

Usage:
  from upstox.instruments import get_instrument_key, get_instrument_keys_bulk
  key = await get_instrument_key("RELIANCE")   # → "NSE_EQ|INE002A01018"
"""

import csv
import gzip
import io
import logging
from typing import Optional

import httpx

from redis_client import get_redis

logger = logging.getLogger(__name__)

# Upstox instruments master URL (NSE equities)
INSTRUMENTS_URL = "https://assets.upstox.com/market-quote/instruments/exchange/NSE.csv.gz"

# Redis key and TTL
_REDIS_KEY = "upstox:instruments:nse"
_REDIS_TTL = 86400  # 24 hours

# In-process cache: symbol → instrument_key
# Populated on first call, invalidated when Redis key expires
_symbol_map: dict[str, str] = {}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def get_instrument_key(symbol: str) -> Optional[str]:
    """
    Returns Upstox instrument_key for a given NSE trading symbol.

    Args:
        symbol: NSE ticker e.g. "RELIANCE", "INFY", "NIFTY50"

    Returns:
        instrument_key string or None if symbol not found
    """
    await _ensure_loaded()
    key = _symbol_map.get(symbol.upper().strip())
    if not key:
        logger.warning("Symbol '%s' not found in instruments master", symbol)
    return key


async def get_instrument_keys_bulk(symbols: list[str]) -> dict[str, Optional[str]]:
    """
    Returns a dict of {symbol: instrument_key} for a list of symbols.
    Missing symbols map to None.

    Args:
        symbols: list of NSE tickers

    Returns:
        dict mapping each symbol to its instrument_key (or None)
    """
    await _ensure_loaded()
    return {
        sym.upper().strip(): _symbol_map.get(sym.upper().strip())
        for sym in symbols
    }


async def search_instruments(query: str, limit: int = 20) -> list[dict]:
    """
    Search instruments by partial symbol or company name.

    Args:
        query: partial symbol or company name
        limit: max results to return

    Returns:
        list of instrument dicts with keys: symbol, instrument_key, name, isin
    """
    await _ensure_loaded()
    q = query.upper().strip()
    results = []

    for symbol, meta in _symbol_meta.items():
        if q in symbol or q in meta.get("name", "").upper():
            results.append({
                "symbol": symbol,
                "instrument_key": meta["instrument_key"],
                "name": meta["name"],
                "isin": meta["isin"],
            })
            if len(results) >= limit:
                break

    return results


async def reload_instruments() -> int:
    """
    Force-reload instruments from Upstox (clears Redis cache + in-memory map).
    Returns the number of NSE_EQ symbols loaded.
    """
    redis = await get_redis()
    await redis.delete(_REDIS_KEY)
    _symbol_map.clear()
    _symbol_meta.clear()
    await _ensure_loaded()
    return len(_symbol_map)


# ---------------------------------------------------------------------------
# Internal state and loader
# ---------------------------------------------------------------------------

# Extended metadata map: symbol → {instrument_key, name, isin}
_symbol_meta: dict[str, dict] = {}
_loaded = False


async def _ensure_loaded() -> None:
    """Load instruments into memory if not already loaded."""
    global _loaded
    if _loaded and _symbol_map:
        return
    await _load_instruments()


async def _load_instruments() -> None:
    """
    Load NSE instruments into _symbol_map and _symbol_meta.

    Strategy:
      1. Try Redis cache first (fast path, ~1 ms)
      2. If not in Redis, download from Upstox, parse, cache in Redis
    """
    global _loaded

    redis = await get_redis()
    cached = await redis.get(_REDIS_KEY)  # str because decode_responses=True

    if cached:
        logger.info("Loading instruments from Redis cache")
        _parse_csv_bytes(cached)
    else:
        logger.info("Downloading instruments master from Upstox…")
        raw = await _download_instruments()
        # decode bytes → str for Redis storage (client uses decode_responses=True)
        raw_str = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else raw
        _parse_csv_bytes(raw_str)
        await redis.set(_REDIS_KEY, raw_str, ex=_REDIS_TTL)
        logger.info(
            "Cached %d NSE_EQ symbols in Redis (TTL %dh)",
            len(_symbol_map),
            _REDIS_TTL // 3600,
        )

    _loaded = True
    logger.info("Instruments loaded: %d NSE_EQ symbols", len(_symbol_map))


async def _download_instruments() -> bytes:
    """Download and decompress the Upstox instruments CSV.gz file."""
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        resp = await client.get(INSTRUMENTS_URL)

    if resp.status_code != 200:
        raise RuntimeError(
            f"Failed to download instruments master: HTTP {resp.status_code}"
        )

    # File is gzip-compressed
    compressed = resp.content
    try:
        decompressed = gzip.decompress(compressed)
    except gzip.BadGzipFile:
        # Some mirrors serve raw CSV; handle gracefully
        decompressed = compressed

    return decompressed


def _parse_csv_bytes(data: bytes) -> None:
    """
    Parse CSV bytes and populate _symbol_map and _symbol_meta.

    We only index NSE_EQ (equity) instruments to keep the map small and fast.
    Other segment codes (NSE_FO, NSE_CD, etc.) are skipped.
    """
    _symbol_map.clear()
    _symbol_meta.clear()

    text = data if isinstance(data, str) else data.decode("utf-8", errors="replace")
    reader = csv.DictReader(io.StringIO(text))

    # Normalise column names (Upstox occasionally renames them)
    # Expected columns: instrument_key, tradingsymbol, name, exchange, instrument_type, isin, lot_size
    count = 0
    for row in reader:
        # Normalise whitespace in keys
        row = {k.strip(): v.strip() for k, v in row.items()}

        instrument_key = row.get("instrument_key", "")
        symbol = row.get("tradingsymbol", "").upper()
        name = row.get("name", "")
        isin = row.get("isin", "")
        instrument_type = row.get("instrument_type", "")

        # Only NSE equities (skip futures, options, currency, etc.)
        if not instrument_key.startswith("NSE_EQ"):
            continue
        if instrument_type not in ("", "EQ", "EQUITY"):
            continue
        if not symbol:
            continue

        _symbol_map[symbol] = instrument_key
        _symbol_meta[symbol] = {
            "instrument_key": instrument_key,
            "name": name,
            "isin": isin,
        }
        count += 1

    if count == 0:
        logger.warning(
            "No NSE_EQ instruments parsed — check CSV column names. "
            "First 200 chars: %s",
            text[:200],
        )


# ---------------------------------------------------------------------------
# Nifty 200 / Nifty 500 universe helpers
# ---------------------------------------------------------------------------

# These are maintained as static lists. In production you'd fetch from NSE's
# index API (https://www.nseindia.com/api/equity-stockIndices?index=NIFTY%20200)
# For now we seed the most liquid names; the scanner will filter anyway by
# liquidity (volume * close > 2 crore).

NIFTY_200_SYMBOLS: set[str] = {
    "RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK", "HINDUNILVR",
    "SBIN", "BHARTIARTL", "KOTAKBANK", "LT", "BAJFINANCE", "HCLTECH",
    "MARUTI", "AXISBANK", "ASIANPAINT", "SUNPHARMA", "TITAN", "WIPRO",
    "ULTRACEMCO", "NTPC", "POWERGRID", "TECHM", "NESTLEIND", "ADANIENT",
    "ADANIPORTS", "DIVISLAB", "BAJAJFINSV", "COALINDIA", "INDUSINDBK",
    "ONGC", "JSWSTEEL", "TATASTEEL", "GRASIM", "HDFCLIFE", "SBILIFE",
    "CIPLA", "DRREDDY", "APOLLOHOSP", "TATACONSUM", "BPCL", "EICHERMOT",
    "HEROMOTOCO", "BRITANNIA", "SHREECEM", "DABUR", "ICICIPRULI",
    "BAJAJ_AUTO", "MARICO", "GODREJCP", "PIDILITIND", "BERGEPAINT",
    "HAVELLS", "VOLTAS", "MUTHOOTFIN", "CHOLAFIN", "TORNTPHARM",
    "LUPIN", "BIOCON", "ALKEM", "AUROPHARMA", "MANKIND", "ABBOTINDIA",
    "PFIZER", "GLAXO", "NAVINFLUOR", "DEEPAKNTR", "FLUOROCHEM",
    "AAPL", "PVRINOX", "INOXWIND", "TATAPOWER", "ADANIGREEN", "ADANITRANS",
    "CANBK", "BANKBARODA", "PNB", "UNIONBANK", "FEDERALBNK", "IDFCFIRSTB",
    "BANDHANBNK", "RBLBANK", "KARURVYSYA", "CSBBANK",
    "SIEMENS", "ABB", "BHEL", "HAL", "BEL", "COCHINSHIP", "MAZDOCK",
    "GRINDWELL", "CUMMINSIND", "THERMAX", "SKFINDIA",
    "DMART", "TRENT", "NYKAA", "ZOMATO", "NAUKRI", "INDIAMART",
    "JUSTDIAL", "IRCTC", "CONCOR",
    "OBEROIRLTY", "DLF", "GODREJPROP", "PRESTIGE", "PHOENIXLTD",
    "PIDILITIND", "ASTRAL", "SUPREMEIND", "ATUL", "BALAMINES",
    "SAIL", "HINDALCO", "VEDL", "NMDC", "MOIL", "NATIONALUM",
    "AMBUJACEM", "ACC", "HEIDELBERG", "RAMCOCEM",
    "MOTHERSON", "BALKRISIND", "APOLLOTYRE", "MRF", "CEATLTD",
    "MFSL", "ICICIGI", "NIACL", "STARHEALTH", "SBICARD",
    "PAGEIND", "WHIRLPOOL", "BLUESTARCO", "BATAINDIA", "VIPIND",
    "ITC", "GODFRYPHLP", "VST", "RADICO",
    "TATACOMM", "MTNL", "RAILTEL",
    "EXIDEIND", "AMARA", "TVSMOTOR", "BAJAJ_AUTO", "ENDURANCE",
    "POLYCAB", "KPITTECH", "LTTS", "PERSISTENT", "COFORGE",
    "MINDTREE", "MPHASIS", "HEXAWARE", "NIITTECH",
    "SRF", "FINOLEX", "CENTURYPLY", "GREENLAM",
    "GODREJIND", "TATAELXSI", "DIXON", "AMBER",
    "ZEEL", "SUNTV", "NETWORK18", "TV18BRDCST",
    "PGHH", "COLPAL", "EMAMILTD",
    "LALPATHLAB", "METROPOLIS", "DRLALPATH", "THYROCARE",
    "CRISIL", "CARE", "ICRA",
    "MCX", "BSE", "CDSL",
    "IRFC", "REC", "PFC", "HUDCO",
    "NHPC", "SJVN", "TORNTPOWER",
}

NIFTY_500_SYMBOLS: set[str] = NIFTY_200_SYMBOLS | {
    # Additional Nifty 500 names beyond Nifty 200
    "APLAPOLLO", "JINDALSAW", "JSWENERGY", "JPPOWER", "TORNTPOWER",
    "RPOWER", "SUZLON", "INOXWIND", "ORIENTELEC", "CESC",
    "NSLNISP", "RATNAMANI", "WELCORP", "MANAPPURAM", "IIFL",
    "M&MFIN", "MAHINDCIE", "SCHAEFFLER", "TIMKEN", "NRB",
    "KPRMILL", "ARVIND", "RAYMOND", "TRIDENT", "WELSPUNIND",
    "HIMATSEIDE", "VARDHMAN", "SPORTKING",
    "AGROPHOS", "COROMANDEL", "CHAMBAL", "GNFC", "GSFC",
    "TATACHEM", "GHCL", "VINDHYATEL",
    "IPCALAB", "NATCOPHARM", "GLENMARK", "GRANULES", "SEQUENT",
    "SUDARSCHEM", "AARTI", "VINATIORGA", "ALKYLAMINE",
    "DELTACORP", "MAHSEAMLES", "SUNTECK", "KOLTEPATIL",
    "SOBHA", "BRIGADE", "HOMEFIRST", "APTUS", "AAVAS",
    "CREDITACC", "SPANDANA", "UJJIVANSFB", "EQUITASBNK",
    "SURYODAY", "ESAFSFB", "UTKARSHBNK",
    "HAPPSTMNDS", "LATENTVIEW", "ROUTE", "INTELLECT",
    "TANLA", "MASTEK", "SONATSOFTW", "RATEGAIN",
    "CAMPUS", "METRO", "VEDANT", "MANYAVAR",
    "PRINCEPIPE", "FINOLEX", "HATSUN", "DODLA",
    "WESTLIFE", "DEVYANI", "SAPPHIRE", "JUBLFOOD",
    "EVEREADY", "GILLETTE", "HSCL", "JUBLPHARMA",
    "GLAND", "SOLARA", "LAURUS", "STRIDES",
    "KRBL", "LT Foods", "PATANJALI", "BIKAJI",
    "ZYDUSLIFE", "LAURUSLABS", "CAPLIPOINT",
    "KFINTECH", "CAMS", "ANAND",
    "MEDPLUS", "RAINBOW", "KIMS", "YATHARTH",
    "SENCO", "KALYAN", "THANGAMAYL",
    "ZENSARTECH", "NEWGEN", "RAMKY",
}


async def get_nifty200_instrument_keys() -> dict[str, str]:
    """Returns {symbol: instrument_key} for all Nifty 200 symbols found in master."""
    result = await get_instrument_keys_bulk(list(NIFTY_200_SYMBOLS))
    return {k: v for k, v in result.items() if v is not None}


async def get_nifty500_instrument_keys() -> dict[str, str]:
    """Returns {symbol: instrument_key} for all Nifty 500 symbols found in master."""
    result = await get_instrument_keys_bulk(list(NIFTY_500_SYMBOLS))
    return {k: v for k, v in result.items() if v is not None}
