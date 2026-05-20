# In engine/data_fetch.py — replace _process_symbol function with this:

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
        # Pass symbol so yfinance fallback works if Upstox token missing
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
    