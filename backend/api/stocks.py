"""api/stocks.py — GET /signals endpoints."""
import logging
from datetime import date, datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models.signal import Signal
from upstox.realtime import feed as realtime_feed

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/signals", tags=["signals"])


@router.get("", summary="List signals with optional filters")
async def list_signals(
    signal_date: Optional[date] = Query(None),
    strategy: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    limit: int = Query(100, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> dict:
    if signal_date is None:
        signal_date = datetime.now(timezone.utc).date()
    stmt = select(Signal).where(Signal.signal_date == signal_date)
    if strategy:
        stmt = stmt.where(Signal.strategy == strategy.upper())
    if status:
        stmt = stmt.where(Signal.status == status.lower())
    stmt = stmt.order_by(desc(Signal.created_at)).offset(offset).limit(limit)
    result = await db.execute(stmt)
    signals = result.scalars().all()
    data = []
    for sig in signals:
        d = sig.to_dict()
        if sig.upstox_key:
            d["ltp"] = realtime_feed.get_ltp(sig.upstox_key)
        data.append(d)
    return {"date": signal_date.isoformat(), "count": len(data), "signals": data}


@router.get("/history", summary="All historical signals with date range")
async def signal_history(
    from_date: Optional[date] = Query(None),
    to_date: Optional[date] = Query(None),
    strategy: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    limit: int = Query(200, le=1000),
    offset: int = Query(0),
    db: AsyncSession = Depends(get_db),
) -> dict:
    stmt = select(Signal)
    if from_date:
        stmt = stmt.where(Signal.signal_date >= from_date)
    if to_date:
        stmt = stmt.where(Signal.signal_date <= to_date)
    if strategy:
        stmt = stmt.where(Signal.strategy == strategy.upper())
    if status:
        stmt = stmt.where(Signal.status == status.lower())
    stmt = stmt.order_by(desc(Signal.signal_date), desc(Signal.created_at)).offset(offset).limit(limit)
    result = await db.execute(stmt)
    signals = result.scalars().all()
    return {"count": len(signals), "signals": [s.to_dict() for s in signals]}


@router.get("/debug/{symbol}", summary="Debug strategy conditions for a symbol")
async def debug_symbol(symbol: str) -> dict:
    """Run both strategies on a symbol and return full condition breakdown."""
    from upstox.instruments import get_instrument_key
    from upstox.historical import fetch_daily_candles_df
    from engine.strategy1 import run_strategy1
    from engine.strategy2 import run_strategy2

    instrument_key = await get_instrument_key(symbol.upper())
    if not instrument_key:
        return {"error": f"Symbol {symbol} not found in instruments master"}
    try:
        df = await fetch_daily_candles_df(instrument_key)
    except Exception as e:
        return {"error": f"Failed to fetch OHLCV: {str(e)}"}
    if df.empty:
        return {"error": "No OHLCV data returned"}

    s1 = run_strategy1(df)
    s2 = run_strategy2(df)
    return {
        "symbol": symbol.upper(),
        "instrument_key": instrument_key,
        "candles": len(df),
        "close": float(df["close"].iloc[-1]),
        "volume": int(df["volume"].iloc[-1]),
        "s1": {
            "signal": s1.signal,
            "conditions": s1.reasons,
            "levels": vars(s1.levels) if s1.levels else None,
        },
        "s2": {
            "signal": s2.signal,
            "conditions": s2.reasons,
            "levels": vars(s2.levels) if s2.levels else None,
        },
    }


@router.get("/{signal_id}", summary="Get single signal detail")
async def get_signal(signal_id: int, db: AsyncSession = Depends(get_db)) -> dict:
    result = await db.execute(select(Signal).where(Signal.id == signal_id))
    sig = result.scalar_one_or_none()
    if not sig:
        raise HTTPException(status_code=404, detail=f"Signal {signal_id} not found")
    d = sig.to_dict()
    if sig.upstox_key:
        d["ltp"] = realtime_feed.get_ltp(sig.upstox_key)
    return d


@router.patch("/{signal_id}/status", summary="Manually update signal status")
async def update_signal_status(
    signal_id: int,
    status: str,
    db: AsyncSession = Depends(get_db),
) -> dict:
    valid = {"active", "hit_t1", "hit_t2", "stopped", "time_stop"}
    if status not in valid:
        raise HTTPException(status_code=400, detail=f"status must be one of {valid}")
    result = await db.execute(select(Signal).where(Signal.id == signal_id))
    sig = result.scalar_one_or_none()
    if not sig:
        raise HTTPException(status_code=404, detail=f"Signal {signal_id} not found")
    sig.status = status
    await db.commit()
    return {"id": signal_id, "status": status}
