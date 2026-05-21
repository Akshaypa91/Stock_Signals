"""
upstox/instruments.py
=====================
Loads NSE instruments from bundled CSV file (NSE_instruments.csv).
Render blocks outbound calls to Upstox CDN, so we bundle the CSV directly.

To update instruments (monthly):
  cd backend/upstox
  curl -L "https://assets.upstox.com/market-quote/instruments/exchange/NSE.csv.gz" -o NSE_instruments.csv.gz
  gunzip -f NSE_instruments.csv.gz
  git add NSE_instruments.csv
  git commit -m "update NSE instruments master"
"""

import csv
import io
import logging
import os
import re
from pathlib import Path
from typing import Optional

from redis_client import get_redis

logger = logging.getLogger(__name__)

# Path to bundled CSV — same directory as this file
_CSV_PATH = Path(__file__).parent / "NSE_instruments.csv"

_REDIS_KEY = "upstox:instruments:nse_v2"
_REDIS_TTL = 86400

_symbol_map:  dict[str, str]  = {}
_symbol_meta: dict[str, dict] = {}
_loaded = False

_VALID_SYMBOL = re.compile(r'^[A-Z0-9&\-]{1,20}$')


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def get_instrument_key(symbol: str) -> Optional[str]:
    await _ensure_loaded()
    key = _symbol_map.get(symbol.upper().strip())
    if not key:
        logger.warning("Symbol '%s' not found in instruments master", symbol)
    return key


async def get_instrument_keys_bulk(symbols: list[str]) -> dict[str, Optional[str]]:
    await _ensure_loaded()
    return {sym: _symbol_map.get(sym.upper().strip()) for sym in symbols}


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
    global _loaded
    _symbol_map.clear()
    _symbol_meta.clear()
    _loaded = False
    # Clear Redis cache so it re-reads from CSV
    try:
        redis = await get_redis()
        await redis.delete(_REDIS_KEY)
    except Exception:
        pass
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

    # Try Redis cache first
    try:
        redis = await get_redis()
        cached = await redis.get(_REDIS_KEY)
        if cached:
            logger.info("Loading instruments from Redis cache")
            _parse_csv_text(cached)
            _loaded = True
            logger.info("Instruments ready: %d symbols (from Redis)", len(_symbol_map))
            return
    except Exception as e:
        logger.warning("Redis read failed: %s — loading from CSV file", e)

    # Load from bundled CSV file
    if not _CSV_PATH.exists():
        logger.error(
            "NSE_instruments.csv not found at %s\n"
            "Run this on your Mac and commit the file:\n"
            "  cd backend/upstox\n"
            "  curl -L 'https://assets.upstox.com/market-quote/instruments/exchange/NSE.csv.gz' -o NSE_instruments.csv.gz\n"
            "  gunzip -f NSE_instruments.csv.gz\n"
            "  git add NSE_instruments.csv && git commit -m 'add NSE instruments'",
            _CSV_PATH,
        )
        _loaded = True
        return

    logger.info("Loading instruments from bundled CSV: %s", _CSV_PATH)
    text = _CSV_PATH.read_text(encoding="utf-8", errors="replace")
    _parse_csv_text(text)

    # Cache in Redis so next startup is faster
    try:
        redis = await get_redis()
        await redis.set(_REDIS_KEY, text, ex=_REDIS_TTL)
    except Exception:
        pass

    _loaded = True
    logger.info("Instruments ready: %d NSE equity symbols", len(_symbol_map))


def _parse_csv_text(text: str) -> None:
    _symbol_map.clear()
    _symbol_meta.clear()

    reader = csv.DictReader(io.StringIO(text))
    count = 0

    for row in reader:
        row = {k.strip(): v.strip() for k, v in row.items() if k}

        instrument_key = row.get("instrument_key", "")
        symbol         = row.get("tradingsymbol", "").upper().strip()
        name           = row.get("name", "")
        lot_size        = row.get("lot_size", "1")
        instrument_type = row.get("instrument_type", "")

        # Filter 1: NSE_EQ only
        if not instrument_key.startswith("NSE_EQ"):
            continue

        # Filter 2: lot_size == 1 (bonds have lot_size=100)
        try:
            if int(lot_size) != 1:
                continue
        except (ValueError, TypeError):
            pass

        # Filter 3: Symbol letters only — no digits
        # ZOMATO✅ BAJAJ-AUTO✅ M&M✅ | 749RJ35❌ 182D110626❌
        import re as _re
        if not symbol or not _re.match(r'^[A-Z][A-Z&\-]{1,19}$', symbol):
            continue

        meta = {"instrument_key": instrument_key, "name": name, "isin": isin}
        _symbol_map[symbol]  = instrument_key
        _symbol_meta[symbol] = meta

        for alias in _get_aliases(symbol):
            if alias not in _symbol_map:
                _symbol_map[alias]  = instrument_key
                _symbol_meta[alias] = meta

        count += 1

    logger.info("Parsed %d NSE equity instruments", count)


def _get_aliases(symbol: str) -> list[str]:
    aliases = []
    if "-" in symbol:
        aliases.append(symbol.replace("-", "_"))
    if "_" in symbol:
        aliases.append(symbol.replace("_", "-"))
    if "&" in symbol:
        aliases.append(symbol.replace("&", ""))
    return aliases


# ---------------------------------------------------------------------------
# Nifty universe
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
    "BANDHANBNK", "RBLBANK", "KARURVYSYA", "SIEMENS", "ABB", "BHEL",
    "HAL", "BEL", "GRINDWELL", "CUMMINSIND", "THERMAX", "SKFINDIA",
    "DMART", "TRENT", "NYKAA", "ZOMATO", "NAUKRI", "INDIAMART",
    "IRCTC", "CONCOR", "OBEROIRLTY", "DLF", "GODREJPROP", "PRESTIGE",
    "ASTRAL", "SUPREMEIND", "ATUL", "SAIL", "HINDALCO", "VEDL",
    "NMDC", "NATIONALUM", "AMBUJACEM", "ACC", "RAMCOCEM", "MOTHERSON",
    "BALKRISIND", "APOLLOTYRE", "MRF", "CEATLTD", "MFSL", "ICICIGI",
    "SBICARD", "ITC", "PAGEIND", "BATAINDIA", "TATACOMM", "POLYCAB",
    "KPITTECH", "LTTS", "PERSISTENT", "COFORGE", "MPHASIS", "TATAELXSI",
    "DIXON", "ZEEL", "SUNTV", "LALPATHLAB", "METROPOLIS", "MCX", "BSE",
    "CDSL", "RECLTD", "PFC", "HUDCO", "IRFC", "NHPC", "SJVN",
    "TORNTPOWER", "PFIZER", "GLAXO", "NAVINFLUOR", "DEEPAKNTR",
    "TATAPOWER", "ADANIGREEN", "M&M",
}

NIFTY_500_SYMBOLS: set[str] = NIFTY_200_SYMBOLS | {
    "APLAPOLLO", "JINDALSAW", "JSWENERGY", "JPPOWER", "SUZLON", "INOXWIND",
    "CESC", "RATNAMANI", "WELCORP", "MANAPPURAM", "M&MFIN", "SCHAEFFLER",
    "TIMKEN", "KPRMILL", "ARVIND", "RAYMOND", "TRIDENT", "WELSPUNLIV",
    "VARDHMAN", "COROMANDEL", "CHAMBALFERT", "GNFC", "GSFC", "TATACHEM",
    "GHCL", "IPCALAB", "NATCOPHARM", "GLENMARK", "GRANULES", "AARTIIND",
    "VINATIORGA", "ALKYLAMINE", "SUNTECK", "KOLTEPATIL", "SOBHA", "BRIGADE",
    "HOMEFIRST", "APTUS", "AAVAS", "CREDITACC", "UJJIVANSFB", "EQUITASBNK",
    "HAPPSTMNDS", "LATENTVIEW", "ROUTE", "INTELLECT", "TANLA", "MASTEK",
    "SONATSOFTW", "CAMPUS", "METROBRAND", "MANYAVAR", "PRINCEPIPE", "HATSUN",
    "DODLA", "WESTLIFE", "DEVYANI", "JUBLFOOD", "JUBLPHARMA", "GLAND",
    "LAURUSLABS", "STRIDES", "KRBL", "BIKAJI", "ZYDUSLIFE", "CAPLIPOINT",
    "KFINTECH", "CAMS", "MEDPLUS", "KIMS", "KALYANKJIL", "THANGAMAYL",
    "ZENSARTECH", "NEWGEN", "SRF", "CENTURYPLY", "GODREJIND", "AMBER",
    "CRISIL", "EXIDEIND", "AMARAJABAT", "TVSMOTOR", "ENDURANCE",
    "HEXAWARE", "NUVAMA", "NETWORK18", "DEEPAKFERT",
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


@instruments_router.post("/reload")
async def reload_instruments_endpoint() -> dict:
    try:
        count = await reload_instruments()
        return {"status": "ok", "symbols_loaded": count}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@instruments_router.get("/search")
async def search_endpoint(q: str, limit: int = 10) -> dict:
    results = await search_instruments(q, limit)
    return {"results": results, "count": len(results)}


@instruments_router.get("/status")
async def instruments_status() -> dict:
    await _ensure_loaded()
    return {
        "loaded": _loaded,
        "total_symbols": len(_symbol_map),
        "csv_exists": _CSV_PATH.exists(),
        "csv_path": str(_CSV_PATH),
        "sample": list(_symbol_map.keys())[:10],
    }