"""models/trade.py — Trade ORM model."""
from datetime import date, datetime
from typing import Optional
from sqlalchemy import Date, DateTime, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column
from database import Base


class Trade(Base):
    __tablename__ = "trades"

    id:           Mapped[int]             = mapped_column(Integer, primary_key=True, autoincrement=True)
    signal_id:    Mapped[Optional[int]]   = mapped_column(Integer, ForeignKey("signals.id", ondelete="SET NULL"), nullable=True, index=True)
    symbol:       Mapped[str]             = mapped_column(String(20), nullable=False, index=True)
    buy_price:    Mapped[float]           = mapped_column(Numeric(10, 2), nullable=False)
    sell_price:   Mapped[Optional[float]] = mapped_column(Numeric(10, 2), nullable=True)
    qty:          Mapped[int]             = mapped_column(Integer, nullable=False)
    exit_qty:     Mapped[Optional[int]]   = mapped_column(Integer, nullable=True)
    pnl:          Mapped[Optional[float]] = mapped_column(Numeric(10, 2), nullable=True)
    pnl_pct:      Mapped[Optional[float]] = mapped_column(Numeric(5, 2), nullable=True)
    exit_reason:  Mapped[Optional[str]]   = mapped_column(String(20), nullable=True)
    entry_date:   Mapped[date]            = mapped_column(Date, nullable=False)
    exit_date:    Mapped[Optional[date]]  = mapped_column(Date, nullable=True)
    hold_days:    Mapped[Optional[int]]   = mapped_column(Integer, nullable=True)
    created_at:   Mapped[datetime]        = mapped_column(DateTime(timezone=True), nullable=False)

    def compute_pnl(self) -> None:
        if self.sell_price and self.buy_price:
            sell = float(self.sell_price)
            buy  = float(self.buy_price)
            qty_for_pnl = self.exit_qty if self.exit_qty else self.qty
            self.pnl     = round((sell - buy) * qty_for_pnl, 2)
            self.pnl_pct = round((sell - buy) / buy * 100, 2)
        if self.entry_date and self.exit_date:
            self.hold_days = (self.exit_date - self.entry_date).days

    def to_dict(self) -> dict:
        return {
            "id":          self.id,
            "signal_id":   self.signal_id,
            "symbol":      self.symbol,
            "buy_price":   float(self.buy_price),
            "sell_price":  float(self.sell_price) if self.sell_price else None,
            "qty":         self.qty,
            "exit_qty":    self.exit_qty,
            "pnl":         float(self.pnl) if self.pnl else None,
            "pnl_pct":     float(self.pnl_pct) if self.pnl_pct else None,
            "exit_reason": self.exit_reason,
            "entry_date":  self.entry_date.isoformat() if self.entry_date else None,
            "exit_date":   self.exit_date.isoformat() if self.exit_date else None,
            "hold_days":   self.hold_days,
            "created_at":  self.created_at.isoformat() if self.created_at else None,
        }
