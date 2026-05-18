"""api/trades.py — Trade CRUD + P&L summary endpoints."""
import logging
from datetime import date, datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models.trade import Trade

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/trades", tags=["trades"])


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------

class TradeCreate(BaseModel):
    signal_id: Optional[int] = None
    symbol: str
    buy_price: float
    qty: int
    entry_date: date


class TradeUpdate(BaseModel):
    sell_price: float
    exit_reason: str    # T1/T2/SL/trail/time_stop/manual
    exit_date: date


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("", summary="Record a new trade entry")
async def create_trade(
    body: TradeCreate,
    db: AsyncSession = Depends(get_db),
) -> dict:
    trade = Trade(
        signal_id=body.signal_id,
        symbol=body.symbol.upper(),
        buy_price=body.buy_price,
        qty=body.qty,
        entry_date=body.entry_date,
        created_at=datetime.now(timezone.utc),
    )
    db.add(trade)
    await db.commit()
    await db.refresh(trade)
    logger.info("Trade created: #%d %s qty=%d @ %.2f", trade.id, trade.symbol, trade.qty, trade.buy_price)
    return trade.to_dict()


@router.put("/{trade_id}", summary="Close a trade (sell)")
async def close_trade(
    trade_id: int,
    body: TradeUpdate,
    db: AsyncSession = Depends(get_db),
) -> dict:
    result = await db.execute(select(Trade).where(Trade.id == trade_id))
    trade = result.scalar_one_or_none()
    if not trade:
        raise HTTPException(status_code=404, detail=f"Trade {trade_id} not found")
    if trade.sell_price:
        raise HTTPException(status_code=400, detail="Trade already closed")

    trade.sell_price = body.sell_price
    trade.exit_reason = body.exit_reason
    trade.exit_date = body.exit_date
    trade.compute_pnl()

    await db.commit()
    await db.refresh(trade)
    logger.info(
        "Trade closed: #%d %s PnL=%.2f (%.2f%%)",
        trade.id, trade.symbol, trade.pnl or 0, trade.pnl_pct or 0,
    )
    return trade.to_dict()


@router.get("", summary="List trades with P&L summary")
async def list_trades(
    from_date: Optional[date] = Query(None),
    to_date: Optional[date] = Query(None),
    symbol: Optional[str] = Query(None),
    exit_reason: Optional[str] = Query(None),
    limit: int = Query(200, le=1000),
    offset: int = Query(0),
    db: AsyncSession = Depends(get_db),
) -> dict:
    stmt = select(Trade)
    if from_date:
        stmt = stmt.where(Trade.entry_date >= from_date)
    if to_date:
        stmt = stmt.where(Trade.entry_date <= to_date)
    if symbol:
        stmt = stmt.where(Trade.symbol == symbol.upper())
    if exit_reason:
        stmt = stmt.where(Trade.exit_reason == exit_reason)

    stmt = stmt.order_by(desc(Trade.entry_date)).offset(offset).limit(limit)
    result = await db.execute(stmt)
    trades = result.scalars().all()

    summary = _compute_summary(trades)
    return {
        "count": len(trades),
        "summary": summary,
        "trades": [t.to_dict() for t in trades],
    }


@router.get("/{trade_id}", summary="Get single trade")
async def get_trade(trade_id: int, db: AsyncSession = Depends(get_db)) -> dict:
    result = await db.execute(select(Trade).where(Trade.id == trade_id))
    trade = result.scalar_one_or_none()
    if not trade:
        raise HTTPException(status_code=404, detail=f"Trade {trade_id} not found")
    return trade.to_dict()


@router.delete("/{trade_id}", summary="Delete a trade record")
async def delete_trade(trade_id: int, db: AsyncSession = Depends(get_db)) -> dict:
    result = await db.execute(select(Trade).where(Trade.id == trade_id))
    trade = result.scalar_one_or_none()
    if not trade:
        raise HTTPException(status_code=404, detail=f"Trade {trade_id} not found")
    await db.delete(trade)
    await db.commit()
    return {"deleted": trade_id}


# ---------------------------------------------------------------------------
# P&L summary helper
# ---------------------------------------------------------------------------

def _compute_summary(trades: list[Trade]) -> dict:
    closed = [t for t in trades if t.sell_price is not None]
    if not closed:
        return {
            "total_trades": len(trades),
            "closed_trades": 0,
            "open_trades": len(trades),
            "win_rate": None,
            "avg_rr": None,
            "total_pnl": 0,
            "best_trade": None,
            "worst_trade": None,
            "avg_hold_days": None,
        }

    pnls = [float(t.pnl or 0) for t in closed]
    wins = [p for p in pnls if p > 0]
    win_rate = round(len(wins) / len(closed) * 100, 1) if closed else 0
    total_pnl = round(sum(pnls), 2)
    best = round(max(pnls), 2) if pnls else 0
    worst = round(min(pnls), 2) if pnls else 0
    hold_days = [t.hold_days for t in closed if t.hold_days is not None]
    avg_hold = round(sum(hold_days) / len(hold_days), 1) if hold_days else None

    return {
        "total_trades": len(trades),
        "closed_trades": len(closed),
        "open_trades": len(trades) - len(closed),
        "win_rate": win_rate,
        "total_pnl": total_pnl,
        "best_trade": best,
        "worst_trade": worst,
        "avg_hold_days": avg_hold,
    }
