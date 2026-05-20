-- Migration 001: Add sl_label and timeframe columns to signals table
-- Run this once against your existing database BEFORE deploying the updated backend.
--
-- Safe to run multiple times (uses IF NOT EXISTS / DO $$ patterns).

DO $$
BEGIN
    -- Add sl_label column: "Good" / "OK" / "Wide — Skip"
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'signals' AND column_name = 'sl_label'
    ) THEN
        ALTER TABLE signals ADD COLUMN sl_label VARCHAR(20);
        RAISE NOTICE 'Added column: sl_label';
    ELSE
        RAISE NOTICE 'Column sl_label already exists — skipped';
    END IF;

    -- Add timeframe column: "Weekly (NSE)" / "Daily (NSE)"
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'signals' AND column_name = 'timeframe'
    ) THEN
        ALTER TABLE signals ADD COLUMN timeframe VARCHAR(20);
        RAISE NOTICE 'Added column: timeframe';
    ELSE
        RAISE NOTICE 'Column timeframe already exists — skipped';
    END IF;
END $$;

-- Backfill sl_label for existing rows based on sl_pct
UPDATE signals
SET sl_label = CASE
    WHEN sl_pct <= 8  THEN 'Good'
    WHEN sl_pct <= 12 THEN 'OK'
    ELSE 'Wide — Skip'
END
WHERE sl_label IS NULL AND sl_pct IS NOT NULL;

-- Backfill timeframe as Daily for all existing rows (they were scanned on daily data)
UPDATE signals
SET timeframe = 'Daily (NSE)'
WHERE timeframe IS NULL;

-- Verify
SELECT
    COUNT(*)                                        AS total_signals,
    COUNT(sl_label)                                 AS has_sl_label,
    COUNT(timeframe)                                AS has_timeframe,
    COUNT(*) FILTER (WHERE sl_label = 'Good')       AS good,
    COUNT(*) FILTER (WHERE sl_label = 'OK')         AS ok,
    COUNT(*) FILTER (WHERE sl_label = 'Wide — Skip') AS wide
FROM signals;
