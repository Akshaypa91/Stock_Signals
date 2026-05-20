"""
engine/strategy2.py
===================
Strategy 2 — Fresh 52-Week Breakout (S2)

Universe  : Nifty 500
Timeframe : Daily OR Weekly candles (set WEEKLY_MODE=true in .env for weekly)

ALL conditions must be true:
  trend_ok    = close > SMA(200) AND close > SMA(50) AND SMA(50) > SMA(200)
  fresh_break = close >= highest(high, 52/252)[yesterday]
                AND close[yesterday] < highest(high, 52/252)[yesterday]
  vol_ok      = volume > SMA(volume, 50) * vol_mult
                  Daily: 2.0x  |  Weekly: 1.5x  (weekly spikes are less frequent)
  move_ok     = close > close[1] * 1.005
  liq_ok      = volume * close > liq_min
                  Daily: Rs.2 Cr (20_000_000)  |  Weekly: Rs.5 Cr (50_000_000)
  price_ok    = close > 50
  sl_width_ok = SL% <= SL_MAX_PCT (default 12%) — pre-checked BEFORE signal fires

Indian Market Notes:
  - NSE trades ~250 days/year → 252 bars for daily 52wk high
  - Weekly chart: 52 bars = 52 weeks (correct for weekly timeframe)
  - Operator-driven volume spikes are common on NSE; 1.5x weekly is more reliable
  - Liquidity threshold raised for weekly to filter illiquid small-caps
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
    rsi,
    highest,
)

logger = logging.getLogger(__name__)

STRATEGY_ID = "S2"

# Resolve weekly mode from env
_weekly = WEEKLY_MODE

# 52-week lookback: 52 bars on weekly chart, 252 bars on daily
HIGH52_BARS: int = 52 if _weekly else 252

# Volume multiplier: 1.5x for weekly (less operator noise), 2.0x for daily
VOL_MULT: float = 1.5 if _weekly else 2.0

# Liquidity: Rs.5 Cr weekly (50_000_000), Rs.2 Cr daily (20_000_000)
LIQ_MIN: float = 50_000_000.0 if _weekly else 20_000_000.0

# Min rows needed
MIN_ROWS: int = HIGH52_BARS + 10


@dataclass
class S2Result:
    signal: bool
    levels: Optional[Levels]
    reasons: dict


def run_strategy2(df: pd.DataFrame, weekly_mode: Optional[bool] = None) -> S2Result:
    """
    Run S2 on a OHLCV DataFrame.

    Args:
        df:          sorted oldest→newest, columns [open, high, low, close, volume]
                     Daily: minimum ~260 rows | Weekly: minimum ~65 rows
        weekly_mode: Override WEEKLY_MODE env flag if provided.

    Returns:
        S2Result with signal=True if all conditions met, plus levels.
    """
    reasons: dict = {}

    # Resolve mode
    is_weekly = _weekly if weekly_mode is None else weekly_mode
    high52_bars = 52 if is_weekly else 252
    vol_mult    = 1.5 if is_weekly else 2.0
    liq_min     = 50_000_000.0 if is_weekly else 20_000_000.0
    min_rows    = high52_bars + 10

    if len(df) < min_rows:
        logger.debug("S2: insufficient data (%d rows, need %d)", len(df), min_rows)
        return S2Result(signal=False, levels=None, reasons={"error": "insufficient_data"})

    close  = df["close"]
    high   = df["high"]
    volume = df["volume"]

    # --- Compute indicators ---
    sma50    = sma(close, 50)
    sma200   = sma(close, 200)
    vol_sma50 = sma(volume.astype(float), 50)
    high52   = highest(high, high52_bars)

    # Latest values
    c      = float(close.iloc[-1])       # today's close
    c_prev = float(close.iloc[-2])       # yesterday's close
    v      = float(volume.iloc[-1])

    s50    = float(sma50.iloc[-1])
    s200   = float(sma200.iloc[-1])
    v_sma50 = float(vol_sma50.iloc[-1])

    # yesterday's 52wk high (BEFORE today's candle) — key for "fresh" break
    h52_yesterday = float(high52.iloc[-2])
    h52_today     = float(high52.iloc[-1])

    # --- Evaluate conditions ---

    # Trend: close > SMA50 > SMA200 (golden alignment)
    trend_ok = (
        c > s200
        and c > s50
        and s50 > s200
        and not (pd.isna(s50) or pd.isna(s200))
    )
    reasons["trend_ok"]  = trend_ok
    reasons["sma50"]     = round(s50, 2)
    reasons["sma200"]    = round(s200, 2)

    # Fresh break: today crosses yesterday's 52wk high for first time
    fresh_break = (
        not pd.isna(h52_yesterday)
        and c >= h52_yesterday
        and c_prev < h52_yesterday
    )
    reasons["fresh_break"]    = fresh_break
    reasons["h52_yesterday"]  = round(h52_yesterday, 2)
    reasons["breakout_pct"]   = round((c / h52_yesterday - 1) * 100, 2)

    # Volume: today > vol_mult × SMA(50)
    # Weekly: 1.5x (NSE weekly volume spikes are less common than daily)
    # Daily:  2.0x
    vol_ok = not pd.isna(v_sma50) and v > v_sma50 * vol_mult
    reasons["vol_ok"]    = vol_ok
    reasons["vol_ratio"] = round(v / v_sma50, 2) if v_sma50 else None
    reasons["vol_mult"]  = vol_mult

    # Momentum: today > yesterday * 1.005 (minimum 0.5% move)
    move_ok = c > c_prev * 1.005
    reasons["move_ok"]      = move_ok
    reasons["day_gain_pct"] = round((c / c_prev - 1) * 100, 2)

    # Liquidity: Rs.5 Cr weekly / Rs.2 Cr daily
    # Filters out illiquid SME and operator-driven micro-caps
    liq_ok = v * c > liq_min
    reasons["liq_ok"]       = liq_ok
    reasons["turnover_cr"]  = round(v * c / 1e7, 2)
    reasons["liq_min_cr"]   = round(liq_min / 1e7, 0)

    # Price filter: avoids penny stocks & SME board stocks
    price_ok = c > 50
    reasons["price_ok"] = price_ok

    # --- SL width pre-check (gates the signal BEFORE calculate_levels) ---
    # Replicates Pine Script: sl_pct_pre = (entry_raw - sl_raw) / entry_raw * 100
    sl_lookback_n = 10 if is_weekly else 5
    entry_raw = c * 1.001
    recent_low = float(df["low"].iloc[-sl_lookback_n:].min())
    sl_raw = max(float(df["low"].iloc[-1]), recent_low) * 0.995
    sl_pct_pre = (entry_raw - sl_raw) / entry_raw * 100
    sl_width_ok = sl_pct_pre <= SL_MAX_PCT
    reasons["sl_width_ok"]  = sl_width_ok
    reasons["sl_pct_pre"]   = round(sl_pct_pre, 2)
    reasons["sl_max_pct"]   = SL_MAX_PCT

    # --- All conditions ---
    all_ok = (
        trend_ok
        and fresh_break
        and vol_ok
        and move_ok
        and liq_ok
        and price_ok
        and sl_width_ok
    )

    if not all_ok:
        failed = [k for k, v in reasons.items() if v is False]
        logger.debug("S2 failed conditions: %s", failed)
        return S2Result(signal=False, levels=None, reasons=reasons)

    # --- Calculate levels ---
    levels = calculate_levels(df, weekly_mode=is_weekly)
    if levels is None:
        # calculate_levels returns None if SL too wide (double safety)
        reasons["sl_width_ok"] = False
        return S2Result(signal=False, levels=None, reasons=reasons)

    logger.info(
        "S2 signal [%s]: close=%.2f h52=%.2f entry=%.2f sl=%.2f(%.1f%%) "
        "t1=%.2f t2=%.2f rr1=%.2f rr2=%.2f qty=%d",
        levels.mode, c, h52_yesterday, levels.entry, levels.sl, levels.sl_pct,
        levels.t1, levels.t2, levels.rr1, levels.rr2, levels.qty,
    )
    return S2Result(signal=True, levels=levels, reasons=reasons)
