"""models/signal.py — Signal ORM model."""
from datetime import date, datetime
from sqlalchemy import Date, DateTime, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column
from database import Base


class Signal(Base):
    __tablename__ = "signals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    upstox_key: Mapped[str] = mapped_column(String(60), nullable=True)
    strategy: Mapped[str] = mapped_column(String(5), nullable=False)      # S1 / S2
    signal_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    entry: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    sl: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    t1: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    t2: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    sl_pct: Mapped[float] = mapped_column(Numeric(5, 2), nullable=True)
    sl_label: Mapped[str] = mapped_column(String(20), nullable=True)      # Good / OK / Wide—Skip
    rr1: Mapped[float] = mapped_column(Numeric(4, 2), nullable=True)
    rr2: Mapped[float] = mapped_column(Numeric(4, 2), nullable=True)
    qty: Mapped[int] = mapped_column(Integer, nullable=True)
    qty_half: Mapped[int] = mapped_column(Integer, nullable=True)
    atr: Mapped[float] = mapped_column(Numeric(10, 2), nullable=True)
    timeframe: Mapped[str] = mapped_column(String(20), nullable=True)     # Weekly (NSE) / Daily (NSE)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "symbol": self.symbol,
            "upstox_key": self.upstox_key,
            "strategy": self.strategy,
            "signal_date": self.signal_date.isoformat() if self.signal_date else None,
            "entry": float(self.entry),
            "sl": float(self.sl),
            "t1": float(self.t1),
            "t2": float(self.t2),
            "sl_pct": float(self.sl_pct) if self.sl_pct else None,
            "sl_label": self.sl_label,
            "rr1": float(self.rr1) if self.rr1 else None,
            "rr2": float(self.rr2) if self.rr2 else None,
            "qty": self.qty,
            "qty_half": self.qty_half,
            "atr": float(self.atr) if self.atr else None,
            "timeframe": self.timeframe,
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
