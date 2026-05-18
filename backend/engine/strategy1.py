"""
engine/strategy1.py
===================
Strategy 1 — Near 52-Week High (S1)

Universe  : Nifty 200
Timeframe : Daily candles

ALL conditions must be true:
  trend_ok  = close > SMA(200) AND close > SMA(50) AND SMA(50) > SMA(200)
  near_high = close >= highest(high, 250) * 0.97
              AND close <= highest(high, 250) * 1.03
  rsi_ok    = RSI(14) > 55 AND RSI(14) < 78
  vol_ok    = volume > SMA(volume, 20) * 2.0
  month_ok  = close > close[21] * 1.08          (21 trading days ≈ 1 month)
  liq_ok    = volume * close > 20_000_000       (2 crore daily turnover)
  fresh_ok  = close > close[1] * 1.005          (today > yesterday * 1.005)
  price_ok  = close > 50
"""

import logging
from dataclasses import dataclass
from typing import Optional

import pandas as pd

from engine.levels import (
    Levels,
    calculate_levels,
    sma,
    ema,
    rsi,
    highest,
)

logger = logging.getLogger(__name__)

STRATEGY_ID = "S1"


@dataclass
class S1Result:
    signal: bool
    levels: Optional[Levels]
    reasons: dict   # condition name → bool/float for debugging


def run_strategy1(df: pd.DataFrame) -> S1Result:
    """
    Run S1 on a OHLCV DataFrame.

    Args:
        df: sorted oldest→newest, columns [open, high, low, close, volume]
            Minimum ~260 rows needed for all indicators.

    Returns:
        S1Result with signal=True if all conditions met, plus levels.
    """
    reasons: dict = {}

    if len(df) < 260:
        logger.debug("S1: insufficient data (%d rows)", len(df))
        return S1Result(signal=False, levels=None, reasons={"error": "insufficient_data"})

    close = df["close"]
    high = df["high"]
    volume = df["volume"]

    # --- Compute indicators ---
    sma50 = sma(close, 50)
    sma200 = sma(close, 200)
    rsi14 = rsi(close, 14)
    vol_sma20 = sma(volume.astype(float), 20)
    high250 = highest(high, 250)

    # Latest values (iloc[-1] = today)
    c = float(close.iloc[-1])
    c_prev = float(close.iloc[-2])         # yesterday
    c_21ago = float(close.iloc[-22]) if len(df) >= 22 else None   # ~1 month ago
    v = float(volume.iloc[-1])

    s50 = float(sma50.iloc[-1])
    s200 = float(sma200.iloc[-1])
    r14 = float(rsi14.iloc[-1])
    v_sma20 = float(vol_sma20.iloc[-1])
    h250 = float(high250.iloc[-1])

    # --- Evaluate conditions ---

    # Trend: close > SMA50 > SMA200
    trend_ok = (
        c > s200
        and c > s50
        and s50 > s200
        and not (pd.isna(s50) or pd.isna(s200))
    )
    reasons["trend_ok"] = trend_ok
    reasons["sma50"] = round(s50, 2)
    reasons["sma200"] = round(s200, 2)

    # Near 52-week high: within ±3%
    near_high = (
        not pd.isna(h250)
        and c >= h250 * 0.97
        and c <= h250 * 1.03
    )
    reasons["near_high"] = near_high
    reasons["high250"] = round(h250, 2)
    reasons["near_high_pct"] = round((c / h250 - 1) * 100, 2) if h250 else None

    # RSI: 55 < RSI < 78
    rsi_ok = not pd.isna(r14) and 55 < r14 < 78
    reasons["rsi_ok"] = rsi_ok
    reasons["rsi14"] = round(r14, 2)

    # Volume: today > 2× SMA(20)
    vol_ok = not pd.isna(v_sma20) and v > v_sma20 * 2.0
    reasons["vol_ok"] = vol_ok
    reasons["vol_ratio"] = round(v / v_sma20, 2) if v_sma20 else None

    # Monthly momentum: +8% vs 21 days ago
    month_ok = (
        c_21ago is not None
        and c_21ago > 0
        and c > c_21ago * 1.08
    )
    reasons["month_ok"] = month_ok
    reasons["month_gain_pct"] = round((c / c_21ago - 1) * 100, 2) if c_21ago else None

    # Liquidity: daily turnover > 2 crore
    liq_ok = v * c > 20_000_000
    reasons["liq_ok"] = liq_ok
    reasons["turnover_cr"] = round(v * c / 1e7, 2)

    # Fresh move: today > yesterday * 1.005
    fresh_ok = c > c_prev * 1.005
    reasons["fresh_ok"] = fresh_ok
    reasons["day_gain_pct"] = round((c / c_prev - 1) * 100, 2)

    # Price filter
    price_ok = c > 50
    reasons["price_ok"] = price_ok

    # --- All conditions ---
    all_ok = (
        trend_ok
        and near_high
        and rsi_ok
        and vol_ok
        and month_ok
        and liq_ok
        and fresh_ok
        and price_ok
    )

    if not all_ok:
        failed = [k for k, v in reasons.items() if v is False]
        logger.debug("S1 failed conditions: %s", failed)
        return S1Result(signal=False, levels=None, reasons=reasons)

    # --- Calculate levels ---
    levels = calculate_levels(df)
    if levels is None:
        return S1Result(signal=False, levels=None, reasons=reasons)

    logger.info(
        "S1 signal: close=%.2f entry=%.2f sl=%.2f t1=%.2f t2=%.2f rr1=%.2f",
        c, levels.entry, levels.sl, levels.t1, levels.t2, levels.rr1,
    )
    return S1Result(signal=True, levels=levels, reasons=reasons)
