"""
api/webhook.py
==============
POST /webhook/chartink — receives Chartink scanner alerts.

Chartink sends:
  {
    "scan_name": "Strategy 1 Breakout",
    "scan_url": "...",
    "triggered_at": "15:35:00",
    "stocks": "RELIANCE,INFY,TCS",
    "trigger_prices": "2450.5,1823.0,3940.0"
  }
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from pydantic import BaseModel, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from engine.data_fetch import run_pipeline, SavedSignal
from api.websocket_manager import ws_manager

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/webhook", tags=["webhook"])


class ChartinkPayload(BaseModel):
    scan_name: Optional[str] = None
    scan_url: Optional[str] = None
    triggered_at: Optional[str] = None
    stocks: str                        # "RELIANCE,INFY,TCS"
    trigger_prices: Optional[str] = None

    @field_validator("stocks")
    @classmethod
    def parse_stocks(cls, v: str) -> str:
        # Accept both comma-separated and space-separated
        return v.replace(" ", ",")

    def get_symbols(self) -> list[str]:
        return [s.strip().upper() for s in self.stocks.split(",") if s.strip()]


@router.post("/chartink", summary="Receive Chartink scanner alert")
async def chartink_webhook(
    payload: ChartinkPayload,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
) -> dict:
    symbols = payload.get_symbols()

    if not symbols:
        raise HTTPException(status_code=400, detail="No symbols in payload")

    logger.info(
        "Chartink webhook: scan='%s' symbols=%s",
        payload.scan_name, symbols,
    )

    # Run pipeline in background so webhook returns immediately
    background_tasks.add_task(
        _pipeline_and_broadcast, symbols, db, payload.scan_name or "chartink"
    )

    return {
        "status": "accepted",
        "symbols_received": len(symbols),
        "symbols": symbols,
    }


async def _pipeline_and_broadcast(
    symbols: list[str],
    db: AsyncSession,
    source: str,
) -> None:
    """Run pipeline and broadcast new signals to WebSocket clients."""
    try:
        saved: list[SavedSignal] = await run_pipeline(symbols, db)
        await db.commit()

        if saved:
            await ws_manager.broadcast({
                "type": "new_signals",
                "source": source,
                "count": len(saved),
                "signals": [
                    {
                        "id": s.id,
                        "symbol": s.symbol,
                        "strategy": s.strategy,
                        "entry": s.entry,
                        "sl": s.sl,
                        "t1": s.t1,
                        "t2": s.t2,
                        "sl_pct": s.sl_pct,
                        "rr1": s.rr1,
                        "rr2": s.rr2,
                        "qty": s.qty,
                        "qty_half": s.qty_half,
                        "atr": s.atr,
                        "status": s.status,
                        "signal_date": s.signal_date.isoformat(),
                    }
                    for s in saved
                ],
            })
            logger.info("Broadcast %d new signals", len(saved))
        else:
            logger.info("Pipeline ran but no new signals for: %s", symbols)

    except Exception as exc:
        logger.exception("Pipeline error for %s: %s", symbols, exc)
