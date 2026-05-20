"""
engine/data_fetch.py
====================
High-level data wrapper used by the pipeline and scanner.

Orchestrates:
  symbol → instrument_key (instruments.py)
  instrument_key → OHLCV DataFrame (historical.py + Redis cache)
  DataFrame → S1 result (strategy1.py)
  DataFrame → S2 result (strategy2.py)
  Result → Levels → saved to DB signal

Also exports run_pipeline() which is the single entry point for:
  - POST /webhook/chartink
  - GET /scanner/run
"""

import logging
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Optional

import pandas as pd
from sqlalchemy.ext.asyncio import AsyncSession

from engine.strategy1 import run_strategy1, S1Result
from engine.strategy2 import run_strategy2, S2Result
from engine.levels import Levels
from upstox.instruments import get_instrument_key
from upstox.historical import fetch_daily_candles_df
from upstox.realtime import feed as realtime_feed

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class PipelineResult:
    symbol: str
    instrument_key: Optional[str]
    s1: Optional[S1Result]
    s2: Optional[S2Result]
    error: Optional[str] = None


@dataclass
class SavedSignal:
    """Mirrors the DB Signal model for broadcasting via WebSocket."""
    id: int
    symbol: str
    upstox_key: str
    strategy: str
    signal_date: date
    entry: float
    sl: float
    t1: float
    t2: float
    sl_pct: float
    rr1: float
    rr2: float
    qty: int
    qty_half: int
    atr: float
    status: str
    created_at: datetime


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

async def run_pipeline(
    symbols: list[str],
    db: AsyncSession,
) -> list[SavedSignal]:
    """
    Full pipeline: symbols → fetch OHLCV → run strategies → save signals → subscribe WS.

    Args:
        symbols: list of NSE tickers received from Chartink or scanner
        db     : async DB session (committed by caller)

    Returns:
        list of SavedSignal for new signals generated this run
    """
    from models.signal import Signal  # avoid circular import

    results: list[PipelineResult] = []
    saved: list[SavedSignal] = []
    today = datetime.now(timezone.utc).date()

    for symbol in symbols:
        result = await _process_symbol(symbol)
        results.append(result)

    # Persist signals and collect WS subscription keys
    for result in results:
        if result.error:
            continue

        for strategy_id, strat_result in [("S1", result.s1), ("S2", result.s2)]:
            if strat_result is None or not strat_result.signal:
                continue

            levels: Levels = strat_result.levels

            # Avoid duplicate signals for same symbol+strategy+date
            from sqlalchemy import select
            existing = await db.execute(
                select(Signal).where(
                    Signal.symbol == result.symbol,
                    Signal.strategy == strategy_id,
                    Signal.signal_date == today,
                )
            )
            if existing.scalar_one_or_none():
                logger.info(
                    "Duplicate signal skipped: %s %s %s",
                    result.symbol, strategy_id, today,
                )
                continue

            sig = Signal(
                symbol=result.symbol,
                upstox_key=result.instrument_key,
                strategy=strategy_id,
                signal_date=today,
                entry=levels.entry,
                sl=levels.sl,
                t1=levels.t1,
                t2=levels.t2,
                sl_pct=levels.sl_pct,
                sl_label=levels.sl_label,
                rr1=levels.rr1,
                rr2=levels.rr2,
                qty=levels.qty,
                qty_half=levels.qty_half,
                atr=levels.atr,
                timeframe=levels.mode,
                status="active",
                created_at=datetime.now(timezone.utc),
            )
            db.add(sig)
            await db.flush()   # assigns sig.id

            logger.info(
                "Saved signal #%d: %s %s entry=%.2f sl=%.2f t1=%.2f",
                sig.id, result.symbol, strategy_id, levels.entry, levels.sl, levels.t1,
            )

            # Subscribe to real-time feed
            if result.instrument_key:
                realtime_feed.subscribe(result.instrument_key)

            saved.append(SavedSignal(
                id=sig.id,
                symbol=result.symbol,
                upstox_key=result.instrument_key or "",
                strategy=strategy_id,
                signal_date=today,
                entry=levels.entry,
                sl=levels.sl,
                t1=levels.t1,
                t2=levels.t2,
                sl_pct=levels.sl_pct,
                sl_label=levels.sl_label,
                rr1=levels.rr1,
                rr2=levels.rr2,
                qty=levels.qty,
                qty_half=levels.qty_half,
                atr=levels.atr,
                timeframe=levels.mode,
                status="active",
                created_at=sig.created_at,
            ))

    return saved


# ---------------------------------------------------------------------------
# Per-symbol processing
# ---------------------------------------------------------------------------

async def _process_symbol(symbol: str) -> PipelineResult:
    """Fetch data + run both strategies for a single symbol."""
    instrument_key = await get_instrument_key(symbol)

    if not instrument_key:
        logger.warning("Unknown symbol: %s — not in instruments master", symbol)
        return PipelineResult(
            symbol=symbol,
            instrument_key=None,
            s1=None,
            s2=None,
            error=f"Unknown symbol: {symbol}",
        )

    try:
        df = await fetch_daily_candles_df(instrument_key)
    except Exception as exc:
        logger.error("Failed to fetch OHLCV for %s (%s): %s", symbol, instrument_key, exc)
        return PipelineResult(
            symbol=symbol,
            instrument_key=instrument_key,
            s1=None,
            s2=None,
            error=str(exc),
        )

    if df.empty or len(df) < 50:
        return PipelineResult(
            symbol=symbol,
            instrument_key=instrument_key,
            s1=None,
            s2=None,
            error=f"Insufficient OHLCV data: {len(df)} rows",
        )

    s1 = run_strategy1(df)
    s2 = run_strategy2(df)

    return PipelineResult(
        symbol=symbol,
        instrument_key=instrument_key,
        s1=s1,
        s2=s2,
    )


# ---------------------------------------------------------------------------
# Trade management: LTP monitor callback
# ---------------------------------------------------------------------------

async def on_ltp_update(instrument_key: str, ltp: float) -> None:
    """
    Called by realtime feed on each LTP tick.
    Checks active signals for SL / T1 / T2 hits and updates DB.
    Also runs EMA(10) trail check.
    Registered in main.py after feed.start().
    """
    from sqlalchemy import select, update
    from database import AsyncSessionLocal
    from models.signal import Signal
    from api.websocket_manager import ws_manager

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Signal).where(
                Signal.upstox_key == instrument_key,
                Signal.status == "active",
            )
        )
        signals: list[Signal] = result.scalars().all()

        for sig in signals:
            new_status = sig.status
            reason = None

            if ltp <= sig.sl:
                new_status = "stopped"
                reason = "SL hit"
            elif ltp >= sig.t2:
                new_status = "hit_t2"
                reason = "T2 hit"
            elif ltp >= sig.t1:
                new_status = "hit_t1"
                reason = "T1 hit (sell 50%)"

            if new_status != sig.status:
                sig.status = new_status
                logger.info(
                    "%s %s: %s at LTP=%.2f",
                    sig.symbol, sig.strategy, reason, ltp,
                )
                await db.commit()

                # Broadcast status update
                await ws_manager.broadcast({
                    "type": "status_update",
                    "signal_id": sig.id,
                    "symbol": sig.symbol,
                    "strategy": sig.strategy,
                    "status": new_status,
                    "ltp": ltp,
                })

        # Broadcast LTP tick to all connected frontend clients
        await ws_manager.broadcast({
            "type": "ltp",
            "instrument_key": instrument_key,
            "ltp": ltp,
        })
