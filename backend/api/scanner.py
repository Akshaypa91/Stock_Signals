"""api/scanner.py — POST /scanner/run — manual full-universe scan."""
import logging
from fastapi import APIRouter, BackgroundTasks, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from database import get_db
from engine.data_fetch import run_pipeline
from api.websocket_manager import ws_manager

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/scanner", tags=["scanner"])


@router.post("/run", summary="Trigger full NSE scan manually")
async def run_scanner(
    background_tasks: BackgroundTasks,
    universe: str = "both",
    db: AsyncSession = Depends(get_db),
) -> dict:
    # Get symbols directly from loaded instruments map at runtime
    from upstox.instruments import _symbol_map, _ensure_loaded
    await _ensure_loaded()

    # Filter to only primary symbols (no aliases — avoid duplicates)
    # Aliases contain - or _ ; primary symbols are clean letters only
    import re
    PRIMARY_RE = re.compile(r'^[A-Z][A-Z&]{1,19}$')
    symbols = [s for s in _symbol_map.keys() if PRIMARY_RE.match(s)]

    if not symbols:
        # Fallback to hardcoded set if map empty
        from upstox.instruments import ALL_NSE_SYMBOLS
        symbols = list(ALL_NSE_SYMBOLS)

    logger.info(
        "Manual scan triggered: universe=%s symbols=%d", universe, len(symbols)
    )
    background_tasks.add_task(_scan_and_broadcast, symbols, db)

    return {
        "status": "scanning",
        "universe": universe,
        "symbol_count": len(symbols),
        "message": "Scan started in background. Results will appear in /signals.",
    }


@router.get("/status", summary="Get real-time feed status")
async def scanner_status() -> dict:
    from upstox.realtime import feed
    from upstox.instruments import _symbol_map
    return {
        "ws_connected": feed.is_connected,
        "subscribed_instruments": len(feed._subscribed),
        "ltp_cache_size": len(feed.get_all_ltps()),
        "instruments_loaded": len(_symbol_map),
    }


async def _scan_and_broadcast(symbols: list, db: AsyncSession) -> None:
    try:
        BATCH = 20
        all_saved = []
        for i in range(0, len(symbols), BATCH):
            batch = symbols[i: i + BATCH]
            saved = await run_pipeline(batch, db)
            await db.commit()
            all_saved.extend(saved)

        if all_saved:
            await ws_manager.broadcast({
                "type": "scan_complete",
                "count": len(all_saved),
                "signals": [
                    {
                        "id": s.id,
                        "symbol": s.symbol,
                        "strategy": s.strategy,
                        "entry": s.entry,
                        "sl": s.sl,
                        "t1": s.t1,
                        "t2": s.t2,
                        "rr1": s.rr1,
                        "status": s.status,
                    }
                    for s in all_saved
                ],
            })
        logger.info("Scan complete: %d signals", len(all_saved))
    except Exception as exc:
        logger.exception("Scanner error: %s", exc)