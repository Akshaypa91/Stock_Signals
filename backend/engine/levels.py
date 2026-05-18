"""
engine/levels.py
================
Calculates Entry / SL / T1 / T2 / ATR / R:R / Qty for a signal.

Inputs: a pandas DataFrame with columns [open, high, low, close, volume]
        sorted oldest → newest, last row = today's candle.

All formula from spec:
  entry    = close * 1.001
  sl       = max(low, lowest(low, 5)) * 0.995
  sl_dist  = entry - sl
  sl_pct   = (sl_dist / entry) * 100
  t1       = entry + 1.5 * ATR(14)
  t2       = entry + 3.0 * ATR(14)
  rr1      = (t1 - entry) / sl_dist
  rr2      = (t2 - entry) / sl_dist
  qty      = floor((capital * risk_pct/100) / sl_dist)
  qty_half = floor(qty / 2)
"""

import logging
import math
import os
from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# App-level config (overridden by .env)
CAPITAL: float = float(os.getenv("CAPITAL", "200000"))
RISK_PCT: float = float(os.getenv("RISK_PCT", "1.0"))
ATR_LEN: int = int(os.getenv("ATR_LEN", "14"))
SL_LOOKBACK: int = int(os.getenv("SL_LOOKBACK", "5"))


@dataclass
class Levels:
    entry: float
    sl: float
    t1: float
    t2: float
    sl_pct: float
    sl_dist: float
    rr1: float
    rr2: float
    atr: float
    qty: int
    qty_half: int
    close: float


def calculate_levels(df: pd.DataFrame) -> Optional[Levels]:
    """
    Calculate trading levels from OHLCV DataFrame.

    Args:
        df: DataFrame sorted oldest→newest, columns [open,high,low,close,volume]
            Must have at least ATR_LEN + 1 rows.

    Returns:
        Levels dataclass, or None if data insufficient / sl_dist <= 0
    """
    if len(df) < ATR_LEN + SL_LOOKBACK:
        logger.warning(
            "Insufficient data for levels: %d rows (need %d)",
            len(df), ATR_LEN + SL_LOOKBACK,
        )
        return None

    close = float(df["close"].iloc[-1])
    low = float(df["low"].iloc[-1])

    # SL: max(today's low, lowest low of last SL_LOOKBACK candles) * 0.995
    recent_low = float(df["low"].iloc[-SL_LOOKBACK:].min())
    sl_base = max(low, recent_low)
    sl = round(sl_base * 0.995, 2)

    # Entry: close * 1.001
    entry = round(close * 1.001, 2)

    sl_dist = round(entry - sl, 2)
    if sl_dist <= 0:
        logger.warning(
            "sl_dist <= 0 (entry=%.2f, sl=%.2f) — skipping signal", entry, sl
        )
        return None

    # ATR(14) — Wilder's smoothed ATR
    atr = float(_atr(df, ATR_LEN))

    sl_pct = round((sl_dist / entry) * 100, 2)
    t1 = round(entry + 1.5 * atr, 2)
    t2 = round(entry + 3.0 * atr, 2)
    rr1 = round((t1 - entry) / sl_dist, 2)
    rr2 = round((t2 - entry) / sl_dist, 2)

    risk_amount = CAPITAL * (RISK_PCT / 100)
    qty = math.floor(risk_amount / sl_dist)
    qty_half = math.floor(qty / 2)

    return Levels(
        entry=entry,
        sl=sl,
        t1=t1,
        t2=t2,
        sl_pct=sl_pct,
        sl_dist=sl_dist,
        rr1=rr1,
        rr2=rr2,
        atr=round(atr, 2),
        qty=qty,
        qty_half=qty_half,
        close=round(close, 2),
    )


# ---------------------------------------------------------------------------
# ATR helper
# ---------------------------------------------------------------------------

def _atr(df: pd.DataFrame, period: int) -> float:
    """
    Wilder's Average True Range.
    TR = max(high-low, abs(high-prev_close), abs(low-prev_close))
    ATR = Wilder's EMA of TR with period `period` (smoothing = 1/period)
    """
    high = df["high"].values
    low = df["low"].values
    close = df["close"].values

    n = len(close)
    tr = np.empty(n)
    tr[0] = high[0] - low[0]

    for i in range(1, n):
        hl = high[i] - low[i]
        hc = abs(high[i] - close[i - 1])
        lc = abs(low[i] - close[i - 1])
        tr[i] = max(hl, hc, lc)

    # Wilder's smoothing: first ATR = SMA(TR, period)
    if n < period:
        return float(np.mean(tr))

    atr_val = float(np.mean(tr[:period]))
    alpha = 1.0 / period

    for i in range(period, n):
        atr_val = alpha * tr[i] + (1 - alpha) * atr_val

    return atr_val


# ---------------------------------------------------------------------------
# Indicator helpers used by strategy modules
# ---------------------------------------------------------------------------

def sma(series: pd.Series, period: int) -> pd.Series:
    """Simple moving average."""
    return series.rolling(window=period, min_periods=period).mean()


def ema(series: pd.Series, period: int) -> pd.Series:
    """Exponential moving average (pandas default: adjust=True)."""
    return series.ewm(span=period, adjust=False, min_periods=period).mean()


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """
    RSI using Wilder's smoothing method.
    Returns a Series aligned to `series` index.
    """
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()

    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def highest(series: pd.Series, period: int) -> pd.Series:
    """Rolling maximum over `period` bars."""
    return series.rolling(window=period, min_periods=period).max()


def lowest(series: pd.Series, period: int) -> pd.Series:
    """Rolling minimum over `period` bars."""
    return series.rolling(window=period, min_periods=period).min()
