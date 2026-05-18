"""
engine/strategy2.py
===================
Strategy 2 — Fresh 52-Week Breakout (S2)

Universe  : Nifty 500
Timeframe : Daily candles

ALL conditions must be true:
  trend_ok    = close > SMA(200) AND close > SMA(50) AND SMA(50) > SMA(200)
  fresh_break = close >= highest(high, 252)[yesterday]   ← today crosses yesterday's 52wk high
                AND close[yesterday] < highest(high, 252)[yesterday]
  vol_ok      = volume > SMA(volume, 50) * 2.0
  move_ok     = close > close[1] * 1.005
  liq_ok      = volume * close > 20_000_000
  price_ok    = close > 50
"""

import logging
from dataclasses import dataclass
from typing import Optional

import pandas as pd

from engine.levels import (
    Levels,
    calculate_levels,
    sma,
    rsi,
    highest,
)

logger = logging.getLogger(__name__)

STRATEGY_ID = "S2"


@dataclass
class S2Result:
    signal: bool
    levels: Optional[Levels]
    reasons: dict


def run_strategy2(df: pd.DataFrame) -> S2Result:
    """
    Run S2 on a OHLCV DataFrame.

    Args:
        df: sorted oldest→newest, columns [open, high, low, close, volume]
            Minimum ~260 rows needed.

    Returns:
        S2Result with signal=True if all conditions met, plus levels.
    """
    reasons: dict = {}

    if len(df) < 260:
        logger.debug("S2: insufficient data (%d rows)", len(df))
        return S2Result(signal=False, levels=None, reasons={"error": "insufficient_data"})

    close = df["close"]
    high = df["high"]
    volume = df["volume"]

    # --- Compute indicators ---
    sma50 = sma(close, 50)
    sma200 = sma(close, 200)
    vol_sma50 = sma(volume.astype(float), 50)
    high252 = highest(high, 252)

    # Latest values
    c = float(close.iloc[-1])           # today's close
    c_prev = float(close.iloc[-2])      # yesterday's close
    v = float(volume.iloc[-1])

    s50 = float(sma50.iloc[-1])
    s200 = float(sma200.iloc[-1])
    v_sma50 = float(vol_sma50.iloc[-1])

    # yesterday's 52-week high (computed BEFORE today's candle)
    # This is the crucial "fresh break" definition:
    # yesterday's close was BELOW the 52wk high, today's close is AT or ABOVE it
    h252_yesterday = float(high252.iloc[-2])   # rolling max up to yesterday
    h252_today = float(high252.iloc[-1])       # includes today

    # --- Evaluate conditions ---

    # Trend
    trend_ok = (
        c > s200
        and c > s50
        and s50 > s200
        and not (pd.isna(s50) or pd.isna(s200))
    )
    reasons["trend_ok"] = trend_ok
    reasons["sma50"] = round(s50, 2)
    reasons["sma200"] = round(s200, 2)

    # Fresh break: today crosses yesterday's 52wk high for the first time
    # close[yesterday] < highest(high,252)[yesterday]  →  was below the level
    # close[today]     >= highest(high,252)[yesterday]  →  now at or above it
    fresh_break = (
        not pd.isna(h252_yesterday)
        and c >= h252_yesterday
        and c_prev < h252_yesterday
    )
    reasons["fresh_break"] = fresh_break
    reasons["h252_yesterday"] = round(h252_yesterday, 2)
    reasons["breakout_pct"] = round((c / h252_yesterday - 1) * 100, 2)

    # Volume: today > 2× SMA(50)
    vol_ok = not pd.isna(v_sma50) and v > v_sma50 * 2.0
    reasons["vol_ok"] = vol_ok
    reasons["vol_ratio"] = round(v / v_sma50, 2) if v_sma50 else None

    # Momentum: today > yesterday * 1.005
    move_ok = c > c_prev * 1.005
    reasons["move_ok"] = move_ok
    reasons["day_gain_pct"] = round((c / c_prev - 1) * 100, 2)

    # Liquidity
    liq_ok = v * c > 20_000_000
    reasons["liq_ok"] = liq_ok
    reasons["turnover_cr"] = round(v * c / 1e7, 2)

    # Price filter
    price_ok = c > 50
    reasons["price_ok"] = price_ok

    # --- All conditions ---
    all_ok = (
        trend_ok
        and fresh_break
        and vol_ok
        and move_ok
        and liq_ok
        and price_ok
    )

    if not all_ok:
        failed = [k for k, v in reasons.items() if v is False]
        logger.debug("S2 failed conditions: %s", failed)
        return S2Result(signal=False, levels=None, reasons=reasons)

    # --- Calculate levels ---
    levels = calculate_levels(df)
    if levels is None:
        return S2Result(signal=False, levels=None, reasons=reasons)

    logger.info(
        "S2 signal: close=%.2f h252=%.2f entry=%.2f sl=%.2f t1=%.2f t2=%.2f",
        c, h252_yesterday, levels.entry, levels.sl, levels.t1, levels.t2,
    )
    return S2Result(signal=True, levels=levels, reasons=reasons)
