"""
engine/strategy1.py
===================
Strategy 1 — Near 52-Week High (S1)

Universe  : Nifty 200
Timeframe : Daily OR Weekly candles (set WEEKLY_MODE=true in .env for weekly)

ALL conditions must be true:
  trend_ok  = close > SMA(200) AND close > SMA(50) AND SMA(50) > SMA(200)
  near_high = close >= highest(high, 250/52) * 0.97
              AND close <= highest(high, 250/52) * 1.03
  rsi_ok    = RSI(14) > 55 AND RSI(14) < 78
  vol_ok    = volume > SMA(volume, 20) * vol_mult
                Daily: 2.0x  |  Weekly: 1.5x
  month_ok  = close > close[21] * 1.08   (21 trading days ≈ 1 month)
  liq_ok    = volume * close > liq_min
                Daily: Rs.2 Cr (20_000_000)  |  Weekly: Rs.5 Cr (50_000_000)
  fresh_ok  = close > close[1] * 1.005
  price_ok  = close > 50
  sl_width_ok = SL% <= SL_MAX_PCT (default 12%)

Indian Market Notes:
  - Weekly chart uses 52-bar high window (52 weeks = 1 year)
  - Liquidity threshold raised for weekly to filter illiquid small-caps
  - Volume multiplier relaxed for weekly (1.5x) vs daily (2.0x)
"""

import logging
import os
from dataclasses import dataclass
from typing import Optional

import pandas as pd

from engine.levels import (
    Levels,
    calculate_levels,
    SL_MAX_PCT,
    WEEKLY_MODE,
    sma,
    ema,
    rsi,
    highest,
)

logger = logging.getLogger(__name__)

STRATEGY_ID = "S1"

# Resolve weekly mode from env
_weekly = WEEKLY_MODE

# 52-week lookback: 52 bars on weekly, 250 bars on daily
HIGH52_BARS: int = 52 if _weekly else 250

# Volume multiplier: 1.5x weekly, 2.0x daily
VOL_MULT: float = 1.5 if _weekly else 2.0

# Liquidity: Rs.5 Cr weekly, Rs.2 Cr daily
LIQ_MIN: float = 50_000_000.0 if _weekly else 20_000_000.0


@dataclass
class S1Result:
    signal: bool
    levels: Optional[Levels]
    reasons: dict


def run_strategy1(df: pd.DataFrame, weekly_mode: Optional[bool] = None) -> S1Result:
    """
    Run S1 on a OHLCV DataFrame.

    Args:
        df:          sorted oldest→newest, columns [open, high, low, close, volume]
                     Daily: minimum ~260 rows | Weekly: minimum ~65 rows
        weekly_mode: Override WEEKLY_MODE env flag if provided.

    Returns:
        S1Result with signal=True if all conditions met, plus levels.
    """
    reasons: dict = {}

    # Resolve mode
    is_weekly  = _weekly if weekly_mode is None else weekly_mode
    high52_bars = 52 if is_weekly else 250
    vol_mult    = 1.5 if is_weekly else 2.0
    liq_min     = 50_000_000.0 if is_weekly else 20_000_000.0
    min_rows    = high52_bars + 10

    if len(df) < min_rows:
        logger.debug("S1: insufficient data (%d rows, need %d)", len(df), min_rows)
        return S1Result(signal=False, levels=None, reasons={"error": "insufficient_data"})

    close  = df["close"]
    high   = df["high"]
    volume = df["volume"]

    # --- Compute indicators ---
    sma50     = sma(close, 50)
    sma200    = sma(close, 200)
    rsi14     = rsi(close, 14)
    vol_sma20 = sma(volume.astype(float), 20)
    high52    = highest(high, high52_bars)

    # Latest values
    c      = float(close.iloc[-1])
    c_prev = float(close.iloc[-2])
    c_21ago = float(close.iloc[-22]) if len(df) >= 22 else None
    v      = float(volume.iloc[-1])

    s50    = float(sma50.iloc[-1])
    s200   = float(sma200.iloc[-1])
    r14    = float(rsi14.iloc[-1])
    v_sma20 = float(vol_sma20.iloc[-1])
    h52    = float(high52.iloc[-1])

    # --- Evaluate conditions ---

    # Trend: close > SMA50 > SMA200
    trend_ok = (
        c > s200
        and c > s50
        and s50 > s200
        and not (pd.isna(s50) or pd.isna(s200))
    )
    reasons["trend_ok"] = trend_ok
    reasons["sma50"]    = round(s50, 2)
    reasons["sma200"]   = round(s200, 2)

    # Near 52-week high: within ±3%
    near_high = (
        not pd.isna(h52)
        and c >= h52 * 0.97
        and c <= h52 * 1.03
    )
    reasons["near_high"]     = near_high
    reasons["high52"]        = round(h52, 2)
    reasons["near_high_pct"] = round((c / h52 - 1) * 100, 2) if h52 else None

    # RSI: 55 < RSI < 78
    rsi_ok = not pd.isna(r14) and 55 < r14 < 78
    reasons["rsi_ok"] = rsi_ok
    reasons["rsi14"]  = round(r14, 2)

    # Volume: today > vol_mult x SMA(20)
    vol_ok = not pd.isna(v_sma20) and v > v_sma20 * vol_mult
    reasons["vol_ok"]    = vol_ok
    reasons["vol_ratio"] = round(v / v_sma20, 2) if v_sma20 else None
    reasons["vol_mult"]  = vol_mult

    # Monthly momentum: +8% vs 21 days ago
    month_ok = (
        c_21ago is not None
        and c_21ago > 0
        and c > c_21ago * 1.08
    )
    reasons["month_ok"]       = month_ok
    reasons["month_gain_pct"] = round((c / c_21ago - 1) * 100, 2) if c_21ago else None

    # Liquidity: Rs.5 Cr weekly / Rs.2 Cr daily
    liq_ok = v * c > liq_min
    reasons["liq_ok"]      = liq_ok
    reasons["turnover_cr"] = round(v * c / 1e7, 2)
    reasons["liq_min_cr"]  = round(liq_min / 1e7, 0)

    # Fresh move: today > yesterday * 1.005
    fresh_ok = c > c_prev * 1.005
    reasons["fresh_ok"]     = fresh_ok
    reasons["day_gain_pct"] = round((c / c_prev - 1) * 100, 2)

    # Price filter
    price_ok = c > 50
    reasons["price_ok"] = price_ok

    # --- SL width pre-check ---
    sl_lookback_n = 10 if is_weekly else 5
    entry_raw  = c * 1.001
    recent_low = float(df["low"].iloc[-sl_lookback_n:].min())
    sl_raw     = max(float(df["low"].iloc[-1]), recent_low) * 0.995
    sl_pct_pre = (entry_raw - sl_raw) / entry_raw * 100
    sl_width_ok = sl_pct_pre <= SL_MAX_PCT
    reasons["sl_width_ok"] = sl_width_ok
    reasons["sl_pct_pre"]  = round(sl_pct_pre, 2)
    reasons["sl_max_pct"]  = SL_MAX_PCT

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
        and sl_width_ok
    )

    if not all_ok:
        failed = [k for k, v in reasons.items() if v is False]
        logger.debug("S1 failed conditions: %s", failed)
        return S1Result(signal=False, levels=None, reasons=reasons)

    # --- Calculate levels ---
    levels = calculate_levels(df, weekly_mode=is_weekly)
    if levels is None:
        reasons["sl_width_ok"] = False
        return S1Result(signal=False, levels=None, reasons=reasons)

    logger.info(
        "S1 signal [%s]: close=%.2f entry=%.2f sl=%.2f(%.1f%%) "
        "t1=%.2f t2=%.2f rr1=%.2f rr2=%.2f qty=%d",
        levels.mode, c, levels.entry, levels.sl, levels.sl_pct,
        levels.t1, levels.t2, levels.rr1, levels.rr2, levels.qty,
    )
    return S1Result(signal=True, levels=levels, reasons=reasons)
