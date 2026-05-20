"""
engine/data_fetch.py
====================
High-level data wrapper used by the pipeline and scanner.

Orchestrates:
  symbol → instrument_key (instruments.py)
  instrument_key → OHLCV DataFrame (historical.py + Redis cache)
                   Falls back to yfinance if Upstox token missing
  DataFrame → S1 result (strategy1.py)
  DataFrame → S2 result (strategy2.py)
  Result → Levels → saved to DB signal

Single entry point for:
  - POST /webhook/chartink
  - POST /scanner/run
"""

import logging
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Optional

import pandas as pd
from sqlalchemy import select
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
    sl_label: str
    rr1: float
    rr2: float
    qty: int
    qty_half: int
    atr: float
    timeframe: str
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

    saved: list[SavedSignal] = []
    today = datetime.now(timezone.utc).date()

    for symbol in symbols:
        result = await _process_symbol(symbol)

        if result.error:
            logger.debug("Skipping %s: %s", symbol, result.error)
            continue

        for strategy_id, strat_result in [("S1", result.s1), ("S2", result.s2)]:
            if strat_result is None or not strat_result.signal:
                continue

            levels: Levels = strat_result.levels

            # Avoid duplicate signals for same symbol + strategy + date
            existing = await db.execute(
                select(Signal).where(
                    Signal.symbol == result.symbol,
                    Signal.strategy == strategy_id,
                    Signal.signal_date == today,
                )
            )
            if existing.scalar_one_or_none():
                logger.info(
                    "Duplicate skipped: %s %s %s",
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
            await db.flush()  # assigns sig.id

            logger.info(
                "Saved signal #%d: %s %s entry=%.2f sl=%.2f(%.1f%%) t1=%.2f t2=%.2f [%s]",
                sig.id, result.symbol, strategy_id,
                levels.entry, levels.sl, levels.sl_pct,
                levels.t1, levels.t2, levels.mode,
            )

            # Subscribe to real-time LTP feed
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
    """
    Fetch OHLCV + run both strategies for a single symbol.
    Passes symbol to fetch_daily_candles_df so yfinance fallback works
    even when Upstox token is missing.
    """
    instrument_key = await get_instrument_key(symbol)

    if not instrument_key:
        logger.warning("Unknown symbol: %s — not in Upstox instruments master", symbol)
        # Still try yfinance with a dummy key so scan doesn't fully fail
        instrument_key = f"NSE_EQ|{symbol}"

    try:
        # symbol= passed explicitly so yfinance fallback uses correct NSE ticker
        df = await fetch_daily_candles_df(instrument_key, symbol=symbol)
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
        logger.debug(
            "Insufficient data for %s: %d rows (need 50+)", symbol, len(df)
        )
        return PipelineResult(
            symbol=symbol,
            instrument_key=instrument_key,
            s1=None,
            s2=None,
            error=f"Insufficient OHLCV data: {len(df)} rows",
        )

    s1 = run_strategy1(df)
    s2 = run_strategy2(df)

    logger.debug(
        "%s: S1=%s S2=%s",
        symbol,
        "SIGNAL" if s1 and s1.signal else "no",
        "SIGNAL" if s2 and s2.signal else "no",
    )

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
    Checks active signals for SL / T1 / T2 hits and updates DB status.
    Broadcasts status changes and LTP ticks to WebSocket clients.
    Registered in main.py lifespan after feed.start().
    """
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

            if ltp <= float(sig.sl):
                new_status = "stopped"
                reason = "SL hit"
            elif ltp >= float(sig.t2):
                new_status = "hit_t2"
                reason = "T2 hit"
            elif ltp >= float(sig.t1):
                new_status = "hit_t1"
                reason = "T1 hit — sell 50%"

            if new_status != sig.status:
                sig.status = new_status
                logger.info(
                    "%s %s: %s at LTP=%.2f", sig.symbol, sig.strategy, reason, ltp
                )
                await db.commit()

                await ws_manager.broadcast({
                    "type": "status_update",
                    "signal_id": sig.id,
                    "symbol": sig.symbol,
                    "strategy": sig.strategy,
                    "status": new_status,
                    "ltp": ltp,
                    "reason": reason,
                })

        # Broadcast raw LTP tick to frontend for live price display
        await ws_manager.broadcast({
            "type": "ltp",
            "instrument_key": instrument_key,
            "ltp": ltp,
        })