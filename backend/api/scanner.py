"""api/scanner.py — GET /scanner/run — manual full-universe scan."""
import logging

from fastapi import APIRouter, BackgroundTasks, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from engine.data_fetch import run_pipeline
from api.websocket_manager import ws_manager
from upstox.instruments import (
    get_nifty200_instrument_keys,
    get_nifty500_instrument_keys,
    ALL_NSE_SYMBOLS,
    ALL_NSE_SYMBOLS,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/scanner", tags=["scanner"])


@router.post("/run", summary="Trigger full Nifty 200+500 scan manually")
async def run_scanner(
    background_tasks: BackgroundTasks,
    universe: str = "both",   # "n200", "n500", "both"
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    Manually trigger a strategy scan on Nifty 200 + Nifty 500.
    Runs in background — check /signals for results.
    """
    if universe == "n200":
        symbols = list(ALL_NSE_SYMBOLS)
    elif universe == "n500":
        symbols = list(ALL_NSE_SYMBOLS)
    else:
        symbols = list(ALL_NSE_SYMBOLS)   # 500 is superset of 200

    logger.info("Manual scan triggered: universe=%s symbols=%d", universe, len(symbols))
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
    return {
        "ws_connected": feed.is_connected,
        "subscribed_instruments": len(feed._subscribed),
        "ltp_cache_size": len(feed.get_all_ltps()),
    }


async def _scan_and_broadcast(symbols: list[str], db: AsyncSession) -> None:
    try:
        # Process in batches of 20 to avoid overloading Upstox API
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
        logger.info("Manual scan complete: %d signals generated", len(all_saved))
    except Exception as exc:
        logger.exception("Scanner error: %s", exc)
