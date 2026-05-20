"""
upstox/instruments.py
=====================
Maps NSE ticker symbols → Upstox instrument_key (e.g. "NSE_EQ|INE002A01018").

Upstox publishes a master CSV at:
  https://assets.upstox.com/market-quote/instruments/exchange/NSE.csv.gz

Downloads + caches in Redis (TTL 24h) and builds in-memory dict for fast lookup.

Symbol normalization applied:
  BAJAJ-AUTO  → also registered as BAJAJ_AUTO
  M&M         → also registered as MM
  L&T         → also registered as LT
"""

import csv
import gzip
import io
import logging
from typing import Optional

import httpx

from redis_client import get_redis

logger = logging.getLogger(__name__)

INSTRUMENTS_URL = "https://assets.upstox.com/market-quote/instruments/exchange/NSE.csv.gz"

_REDIS_KEY = "upstox:instruments:nse"
_REDIS_TTL = 86400  # 24 hours

# In-process cache
_symbol_map:  dict[str, str]  = {}   # symbol → instrument_key
_symbol_meta: dict[str, dict] = {}   # symbol → {instrument_key, name, isin}
_loaded = False


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def get_instrument_key(symbol: str) -> Optional[str]:
    await _ensure_loaded()
    normalized = _normalize(symbol)
    key = _symbol_map.get(normalized)
    if not key:
        logger.warning("Symbol '%s' not found in instruments master", symbol)
    return key


async def get_instrument_keys_bulk(symbols: list[str]) -> dict[str, Optional[str]]:
    await _ensure_loaded()
    return {
        sym: _symbol_map.get(_normalize(sym))
        for sym in symbols
    }


async def search_instruments(query: str, limit: int = 20) -> list[dict]:
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
    """Force-reload instruments from Upstox. Clears Redis + in-memory cache."""
    global _loaded
    redis = await get_redis()
    await redis.delete(_REDIS_KEY)
    _symbol_map.clear()
    _symbol_meta.clear()
    _loaded = False
    await _ensure_loaded()
    return len(_symbol_map)


# ---------------------------------------------------------------------------
# Internal loader
# ---------------------------------------------------------------------------

async def _ensure_loaded() -> None:
    global _loaded
    if _loaded and _symbol_map:
        return
    await _load_instruments()


async def _load_instruments() -> None:
    global _loaded

    redis = await get_redis()
    cached = await redis.get(_REDIS_KEY)

    if cached:
        logger.info("Loading instruments from Redis cache")
        _parse_csv_text(cached)
    else:
        logger.info("Downloading instruments master from Upstox...")
        raw_bytes = await _download_instruments()
        raw_str   = raw_bytes.decode("utf-8", errors="replace")
        _parse_csv_text(raw_str)
        await redis.set(_REDIS_KEY, raw_str, ex=_REDIS_TTL)
        logger.info("Instruments cached: %d NSE_EQ symbols", len(_symbol_map))

    _loaded = True
    logger.info("Instruments loaded: %d NSE_EQ symbols available", len(_symbol_map))


async def _download_instruments() -> bytes:
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        resp = await client.get(INSTRUMENTS_URL)

    if resp.status_code != 200:
        raise RuntimeError(f"Failed to download instruments: HTTP {resp.status_code}")

    try:
        return gzip.decompress(resp.content)
    except Exception:
        return resp.content  # already plain CSV


def _parse_csv_text(text: str) -> None:
    """
    Parse Upstox NSE CSV and populate _symbol_map + _symbol_meta.
    Only NSE_EQ equities are indexed.
    Also registers normalized aliases (BAJAJ-AUTO → BAJAJ_AUTO etc.)
    """
    _symbol_map.clear()
    _symbol_meta.clear()

    reader = csv.DictReader(io.StringIO(text))
    count = 0

    for row in reader:
        row = {k.strip(): v.strip() for k, v in row.items()}

        instrument_key   = row.get("instrument_key", "")
        symbol           = row.get("tradingsymbol", "").upper().strip()
        name             = row.get("name", "")
        isin             = row.get("isin", "")
        instrument_type  = row.get("instrument_type", "")

        # Only NSE equities
        if not instrument_key.startswith("NSE_EQ"):
            continue
        if instrument_type not in ("", "EQ", "EQUITY"):
            continue
        if not symbol:
            continue

        meta = {"instrument_key": instrument_key, "name": name, "isin": isin}

        # Register primary symbol
        _symbol_map[symbol]  = instrument_key
        _symbol_meta[symbol] = meta

        # Register normalized aliases so both forms work:
        #   BAJAJ-AUTO  ↔  BAJAJ_AUTO
        #   M&M         ↔  MM
        #   M&MFIN      ↔  MMFIN
        for alias in _get_aliases(symbol):
            if alias not in _symbol_map:
                _symbol_map[alias]  = instrument_key
                _symbol_meta[alias] = meta

        count += 1

    if count == 0:
        logger.error(
            "No NSE_EQ instruments parsed! CSV preview: %s", text[:300]
        )


def _normalize(symbol: str) -> str:
    """Normalize symbol for lookup."""
    return symbol.upper().strip()


def _get_aliases(symbol: str) -> list[str]:
    """
    Return alternate forms of a symbol that users might use.
    e.g. BAJAJ-AUTO → [BAJAJ_AUTO], M&M → [MM], LT → [L&T]
    """
    aliases = []

    # Hyphen ↔ underscore
    if "-" in symbol:
        aliases.append(symbol.replace("-", "_"))
    if "_" in symbol:
        aliases.append(symbol.replace("_", "-"))

    # Ampersand removal (M&M → MM, M&MFIN → MMFIN)
    if "&" in symbol:
        aliases.append(symbol.replace("&", ""))

    return aliases


# ---------------------------------------------------------------------------
# Nifty 200 / Nifty 500 universe
# Uses Upstox tradingsymbol format exactly as it appears in instruments master
# ---------------------------------------------------------------------------

NIFTY_200_SYMBOLS: set[str] = {
    # Index heavyweights
    "RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK", "HINDUNILVR",
    "SBIN", "BHARTIARTL", "KOTAKBANK", "LT", "BAJFINANCE", "HCLTECH",
    "MARUTI", "AXISBANK", "ASIANPAINT", "SUNPHARMA", "TITAN", "WIPRO",
    "ULTRACEMCO", "NTPC", "POWERGRID", "TECHM", "NESTLEIND", "ADANIENT",
    "ADANIPORTS", "DIVISLAB", "BAJAJFINSV", "COALINDIA", "INDUSINDBK",
    "ONGC", "JSWSTEEL", "TATASTEEL", "GRASIM", "HDFCLIFE", "SBILIFE",
    "CIPLA", "DRREDDY", "APOLLOHOSP", "TATACONSUM", "BPCL", "EICHERMOT",
    "HEROMOTOCO", "BRITANNIA", "SHREECEM", "DABUR", "ICICIPRULI",
    "BAJAJ-AUTO", "MARICO", "GODREJCP", "PIDILITIND", "BERGEPAINT",
    "HAVELLS", "VOLTAS", "MUTHOOTFIN", "CHOLAFIN", "TORNTPHARM",
    "LUPIN", "BIOCON", "ALKEM", "AUROPHARMA", "MANKIND", "ABBOTINDIA",
    # Banks
    "CANBK", "BANKBARODA", "PNB", "UNIONBANK", "FEDERALBNK", "IDFCFIRSTB",
    "BANDHANBNK", "RBLBANK", "KARURVYSYA",
    # Industrials
    "SIEMENS", "ABB", "BHEL", "HAL", "BEL", "GRINDWELL",
    "CUMMINSIND", "THERMAX", "SKFINDIA",
    # Consumer/retail
    "DMART", "TRENT", "NYKAA", "ZOMATO", "NAUKRI", "INDIAMART",
    "IRCTC", "CONCOR",
    # Real estate
    "OBEROIRLTY", "DLF", "GODREJPROP", "PRESTIGE",
    # Chemicals
    "PIDILITIND", "ASTRAL", "SUPREMEIND", "ATUL",
    # Metals
    "SAIL", "HINDALCO", "VEDL", "NMDC", "NATIONALUM",
    # Cement
    "AMBUJACEM", "ACC", "RAMCOCEM",
    # Auto ancillary
    "MOTHERSON", "BALKRISIND", "APOLLOTYRE", "MRF", "CEATLTD",
    # Insurance/Finance
    "MFSL", "ICICIGI", "SBICARD",
    # FMCG
    "ITC", "PAGEIND", "BATAINDIA",
    # Telecom/IT
    "TATACOMM", "POLYCAB", "KPITTECH", "LTTS", "PERSISTENT", "COFORGE",
    "MPHASIS", "TATAELXSI", "DIXON",
    # Media
    "ZEEL", "SUNTV",
    # Healthcare
    "LALPATHLAB", "METROPOLIS",
    # Financials
    "MCX", "BSE", "CDSL",
    "IRFC", "RECLTD", "PFC", "HUDCO",
    "NHPC", "SJVN", "TORNTPOWER",
    # Pharma
    "PFIZER", "GLAXO", "NAVINFLUOR", "DEEPAKNTR",
    # Energy
    "TATAPOWER", "ADANIGREEN",
}

NIFTY_500_SYMBOLS: set[str] = NIFTY_200_SYMBOLS | {
    # Extended universe
    "APLAPOLLO", "JINDALSAW", "JSWENERGY", "JPPOWER",
    "SUZLON", "INOXWIND", "CESC",
    "RATNAMANI", "WELCORP", "MANAPPURAM",
    "M&MFIN", "SCHAEFFLER", "TIMKEN",
    "KPRMILL", "ARVIND", "RAYMOND", "TRIDENT", "WELSPUNLIV",
    "VARDHMAN",
    "COROMANDEL", "CHAMBALFERT", "GNFC", "GSFC",
    "TATACHEM", "GHCL",
    "IPCALAB", "NATCOPHARM", "GLENMARK", "GRANULES",
    "AARTIIND", "VINATIORGA", "ALKYLAMINE",
    "SUNTECK", "KOLTEPATIL", "SOBHA", "BRIGADE",
    "HOMEFIRST", "APTUS", "AAVAS",
    "CREDITACC", "UJJIVANSFB", "EQUITASBNK",
    "HAPPSTMNDS", "LATENTVIEW", "ROUTE", "INTELLECT",
    "TANLA", "MASTEK", "SONATSOFTW",
    "CAMPUS", "METROBRAND", "MANYAVAR",
    "PRINCEPIPE", "FINPIPE", "HATSUN", "DODLA",
    "WESTLIFE", "DEVYANI", "JUBLFOOD",
    "JUBLPHARMA",
    "GLAND", "LAURUSLABS", "STRIDES",
    "KRBL", "PATANJALI", "BIKAJI",
    "ZYDUSLIFE", "CAPLIPOINT",
    "KFINTECH", "CAMS",
    "MEDPLUS", "KIMS",
    "SENCO", "KALYANKJIL", "THANGAMAYL",
    "ZENSARTECH", "NEWGEN",
    "NSLNISP", "IIFL",
    "HEXAWARE", "NIITTECH",
    "SRF", "CENTURYPLY",
    "GODREJIND", "AMBER",
    "NETWORK18",
    "CRISIL",
    "EXIDEIND", "AMARAJABAT", "TVSMOTOR", "ENDURANCE",
    "RECLTD",
}


async def get_nifty200_instrument_keys() -> dict[str, str]:
    result = await get_instrument_keys_bulk(list(NIFTY_200_SYMBOLS))
    return {k: v for k, v in result.items() if v is not None}


async def get_nifty500_instrument_keys() -> dict[str, str]:
    result = await get_instrument_keys_bulk(list(NIFTY_500_SYMBOLS))
    return {k: v for k, v in result.items() if v is not None}


# ---------------------------------------------------------------------------
# FastAPI router — mount in main.py for admin endpoints
# ---------------------------------------------------------------------------

from fastapi import APIRouter
instruments_router = APIRouter(prefix="/instruments", tags=["instruments"])

@instruments_router.post("/reload", summary="Force reload instruments master from Upstox")
async def reload_instruments_endpoint() -> dict:
    """
    Force-downloads fresh instruments CSV from Upstox.
    Call this if symbols are showing as 'not found'.
    Takes ~3-5 seconds.
    """
    count = await reload_instruments()
    return {
        "status": "ok",
        "symbols_loaded": count,
        "message": f"Loaded {count} NSE_EQ symbols from Upstox instruments master",
    }

@instruments_router.get("/search", summary="Search instruments by symbol or name")
async def search_endpoint(q: str, limit: int = 10) -> dict:
    results = await search_instruments(q, limit)
    return {"results": results, "count": len(results)}

@instruments_router.get("/status", summary="Instruments master status")
async def instruments_status() -> dict:
    await _ensure_loaded()
    return {
        "loaded": _loaded,
        "symbol_count": len(_symbol_map),
        "sample": list(_symbol_map.keys())[:10],
    }