"""
upstox/instruments.py
=====================
Maps NSE ticker symbols → Upstox instrument_key (e.g. "NSE_EQ|INE002A01018").

Upstox publishes a master CSV at:
  https://assets.upstox.com/market-quote/instruments/exchange/NSE.csv.gz

Downloads + caches in Redis (TTL 24h) and builds in-memory dict for fast lookup.

Equity filter: ISIN must start with "INE" (real NSE equities only — filters bonds/tbills)
Symbol alias normalization:
  BAJAJ-AUTO  → also BAJAJ_AUTO
  M&M         → also MM
"""

import csv
import gzip
import io
import logging
import re
from typing import Optional

import httpx

from redis_client import get_redis

logger = logging.getLogger(__name__)

INSTRUMENTS_URL = "https://assets.upstox.com/market-quote/instruments/exchange/NSE.csv.gz"

_REDIS_KEY = "upstox:instruments:nse"
_REDIS_TTL = 86400  # 24 hours

# In-process cache
_symbol_map:  dict[str, str]  = {}
_symbol_meta: dict[str, dict] = {}
_loaded = False

# Regex: valid NSE equity symbols are 1–20 uppercase alphanum + hyphen/ampersand
_VALID_SYMBOL = re.compile(r'^[A-Z0-9&\-]{1,20}$')


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def get_instrument_key(symbol: str) -> Optional[str]:
    await _ensure_loaded()
    key = _symbol_map.get(_normalize(symbol))
    if not key:
        logger.warning("Symbol '%s' not found in instruments master", symbol)
    return key


async def get_instrument_keys_bulk(symbols: list[str]) -> dict[str, Optional[str]]:
    await _ensure_loaded()
    return {sym: _symbol_map.get(_normalize(sym)) for sym in symbols}


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
    try:
        redis = await get_redis()
        await redis.delete(_REDIS_KEY)
    except Exception as e:
        logger.warning("Redis clear failed during reload: %s", e)

    _symbol_map.clear()
    _symbol_meta.clear()
    _loaded = False
    await _load_instruments()
    return len(_symbol_map)


# ---------------------------------------------------------------------------
# Internal loader
# ---------------------------------------------------------------------------

async def _ensure_loaded() -> None:
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
        try:
            raw_bytes = await _download_instruments()
            raw_str   = raw_bytes.decode("utf-8", errors="replace")
            _parse_csv_text(raw_str)
            await redis.set(_REDIS_KEY, raw_str, ex=_REDIS_TTL)
            logger.info("Instruments cached: %d equity symbols", len(_symbol_map))
        except Exception as e:
            logger.error("Failed to download instruments: %s", e)
            _loaded = True  # prevent infinite retry loop
            return

    _loaded = True
    logger.info("Instruments ready: %d NSE equity symbols", len(_symbol_map))


async def _download_instruments() -> bytes:
    async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
        resp = await client.get(INSTRUMENTS_URL)

    if resp.status_code != 200:
        raise RuntimeError(f"Failed to download instruments: HTTP {resp.status_code}")

    try:
        return gzip.decompress(resp.content)
    except Exception:
        return resp.content


def _parse_csv_text(text: str) -> None:
    """
    Parse Upstox NSE CSV.
    Filters: NSE_EQ prefix + ISIN starts with INE (real equities only).
    Bonds, T-Bills, ETFs filtered out.
    """
    _symbol_map.clear()
    _symbol_meta.clear()

    reader = csv.DictReader(io.StringIO(text))
    count = 0

    for row in reader:
        row = {k.strip(): v.strip() for k, v in row.items() if k}

        instrument_key = row.get("instrument_key", "")
        symbol         = row.get("tradingsymbol", "").upper().strip()
        name           = row.get("name", "")
        isin           = row.get("isin", "")
        lot_size       = row.get("lot_size", "1")

        # ── Filter 1: Must be NSE_EQ ──────────────────────────────────────
        if not instrument_key.startswith("NSE_EQ"):
            continue

        # ── Filter 2: ISIN must start with INE (Indian equity ISIN) ──────
        # Bonds: IN0xxx, T-Bills: IN0xxx, ETFs: INFxxx
        # Real equities: INExxx
        if not isin.startswith("INE"):
            continue

        # ── Filter 3: Valid symbol pattern ───────────────────────────────
        if not symbol or not _VALID_SYMBOL.match(symbol):
            continue

        # ── Filter 4: lot_size == 1 (not derivatives) ────────────────────
        try:
            if int(lot_size) != 1:
                continue
        except (ValueError, TypeError):
            pass

        meta = {"instrument_key": instrument_key, "name": name, "isin": isin}

        _symbol_map[symbol]  = instrument_key
        _symbol_meta[symbol] = meta

        # Register aliases
        for alias in _get_aliases(symbol):
            if alias not in _symbol_map:
                _symbol_map[alias]  = instrument_key
                _symbol_meta[alias] = meta

        count += 1

    if count == 0:
        logger.error("No instruments parsed! CSV preview:\n%s", text[:500])
    else:
        logger.info("Parsed %d NSE equity instruments (bonds/ETFs filtered)", count)


def _normalize(symbol: str) -> str:
    return symbol.upper().strip()


def _get_aliases(symbol: str) -> list[str]:
    """Register alternate forms: BAJAJ-AUTO↔BAJAJ_AUTO, M&M↔MM"""
    aliases = []
    if "-" in symbol:
        aliases.append(symbol.replace("-", "_"))
    if "_" in symbol:
        aliases.append(symbol.replace("_", "-"))
    if "&" in symbol:
        aliases.append(symbol.replace("&", ""))
    return aliases


# ---------------------------------------------------------------------------
# Nifty universe sets
# ---------------------------------------------------------------------------

NIFTY_200_SYMBOLS: set[str] = {
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
    "CANBK", "BANKBARODA", "PNB", "UNIONBANK", "FEDERALBNK", "IDFCFIRSTB",
    "BANDHANBNK", "RBLBANK", "KARURVYSYA",
    "SIEMENS", "ABB", "BHEL", "HAL", "BEL", "GRINDWELL",
    "CUMMINSIND", "THERMAX", "SKFINDIA",
    "DMART", "TRENT", "NYKAA", "ZOMATO", "NAUKRI", "INDIAMART",
    "IRCTC", "CONCOR",
    "OBEROIRLTY", "DLF", "GODREJPROP", "PRESTIGE",
    "ASTRAL", "SUPREMEIND", "ATUL",
    "SAIL", "HINDALCO", "VEDL", "NMDC", "NATIONALUM",
    "AMBUJACEM", "ACC", "RAMCOCEM",
    "MOTHERSON", "BALKRISIND", "APOLLOTYRE", "MRF", "CEATLTD",
    "MFSL", "ICICIGI", "SBICARD",
    "ITC", "PAGEIND", "BATAINDIA",
    "TATACOMM", "POLYCAB", "KPITTECH", "LTTS", "PERSISTENT", "COFORGE",
    "MPHASIS", "TATAELXSI", "DIXON",
    "ZEEL", "SUNTV",
    "LALPATHLAB", "METROPOLIS",
    "MCX", "BSE", "CDSL",
    "RECLTD", "PFC", "HUDCO", "IRFC",
    "NHPC", "SJVN", "TORNTPOWER",
    "PFIZER", "GLAXO", "NAVINFLUOR", "DEEPAKNTR",
    "TATAPOWER", "ADANIGREEN",
    "M&M",
}

NIFTY_500_SYMBOLS: set[str] = NIFTY_200_SYMBOLS | {
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
    "PRINCEPIPE", "HATSUN", "DODLA",
    "WESTLIFE", "DEVYANI", "JUBLFOOD",
    "JUBLPHARMA", "GLAND", "LAURUSLABS", "STRIDES",
    "KRBL", "BIKAJI",
    "ZYDUSLIFE", "CAPLIPOINT",
    "KFINTECH", "CAMS",
    "MEDPLUS", "KIMS",
    "KALYANKJIL", "THANGAMAYL",
    "ZENSARTECH", "NEWGEN",
    "SRF", "CENTURYPLY",
    "GODREJIND", "AMBER",
    "CRISIL",
    "EXIDEIND", "AMARAJABAT", "TVSMOTOR", "ENDURANCE",
    "HEXAWARE", "NUVAMA",
    "NETWORK18",
    "DEEPAKFERT",
}


async def get_nifty200_instrument_keys() -> dict[str, str]:
    result = await get_instrument_keys_bulk(list(NIFTY_200_SYMBOLS))
    return {k: v for k, v in result.items() if v is not None}


async def get_nifty500_instrument_keys() -> dict[str, str]:
    result = await get_instrument_keys_bulk(list(NIFTY_500_SYMBOLS))
    return {k: v for k, v in result.items() if v is not None}


# ---------------------------------------------------------------------------
# FastAPI router
# ---------------------------------------------------------------------------

from fastapi import APIRouter
instruments_router = APIRouter(prefix="/instruments", tags=["instruments"])


@instruments_router.post("/reload", summary="Force reload instruments master from Upstox")
async def reload_instruments_endpoint() -> dict:
    """Force-download fresh instruments CSV. Call if symbols show as 'not found'."""
    try:
        count = await reload_instruments()
        return {
            "status": "ok",
            "symbols_loaded": count,
            "message": f"Loaded {count} NSE equity symbols",
        }
    except Exception as e:
        logger.exception("Reload failed: %s", e)
        return {"status": "error", "message": str(e)}


@instruments_router.get("/search", summary="Search instruments by symbol or name")
async def search_endpoint(q: str, limit: int = 10) -> dict:
    results = await search_instruments(q, limit)
    return {"results": results, "count": len(results)}


@instruments_router.get("/status", summary="Instruments master status")
async def instruments_status() -> dict:
    await _ensure_loaded()
    equity_symbols = [s for s in _symbol_map.keys() if _VALID_SYMBOL.match(s) and len(s) <= 15]
    return {
        "loaded": _loaded,
        "total_keys": len(_symbol_map),
        "equity_count": len(equity_symbols),
        "sample_equities": sorted(equity_symbols)[:15],
    }