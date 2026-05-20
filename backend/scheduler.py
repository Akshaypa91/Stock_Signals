"""
scheduler.py
============
Daily job scheduler using APScheduler.

Jobs:
  1. auto_login     — 6:30 AM IST every day (gets fresh Upstox token)
  2. daily_scan     — 9:20 AM IST every weekday (Mon-Fri) after market opens

IST = UTC+5:30, so:
  6:30 AM IST = 1:00 AM UTC
  9:20 AM IST = 3:50 AM UTC

Started in main.py lifespan, stopped on shutdown.
"""

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler(timezone="UTC")


def start_scheduler():
    """Register all jobs and start the scheduler. Called from main.py lifespan."""

    # ── Job 1: Auto-login at 6:30 AM IST (1:00 AM UTC) every day ──────────
    scheduler.add_job(
        _run_auto_login,
        trigger=CronTrigger(hour=1, minute=0),   # 1:00 AM UTC = 6:30 AM IST
        id="upstox_auto_login",
        name="Upstox Auto Login",
        replace_existing=True,
        misfire_grace_time=300,   # allow 5 min late start
    )

    # ── Job 2: Daily scan at 9:20 AM IST (3:50 AM UTC) Mon-Fri ───────────
    # NSE opens 9:15 AM IST — we wait 5 min for price to settle
    scheduler.add_job(
        _run_daily_scan,
        trigger=CronTrigger(hour=3, minute=50, day_of_week="mon-fri"),
        id="daily_scan",
        name="Daily NSE Scan",
        replace_existing=True,
        misfire_grace_time=300,
    )

    scheduler.start()
    logger.info(
        "Scheduler started. Jobs: auto_login @ 6:30 AM IST, scan @ 9:20 AM IST (Mon-Fri)"
    )


def stop_scheduler():
    """Stop scheduler gracefully. Called from main.py lifespan shutdown."""
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")


# ---------------------------------------------------------------------------
# Job runners
# ---------------------------------------------------------------------------

async def _run_auto_login():
    """Daily auto-login job — gets fresh Upstox token."""
    from upstox.auto_login import auto_login
    logger.info("Scheduler: running auto_login job")
    success = await auto_login()
    if success:
        logger.info("Scheduler: auto_login completed successfully")
    else:
        logger.error(
            "Scheduler: auto_login FAILED — manual login required at /upstox/login"
        )


async def _run_daily_scan():
    """Daily scan job — runs strategy scan on Nifty 500."""
    from database import AsyncSessionLocal
    from engine.data_fetch import run_pipeline
    from upstox.instruments import NIFTY_500_SYMBOLS

    logger.info("Scheduler: running daily NSE scan")
    symbols = list(NIFTY_500_SYMBOLS)

    async with AsyncSessionLocal() as db:
        try:
            BATCH = 20
            total = 0
            for i in range(0, len(symbols), BATCH):
                batch = symbols[i: i + BATCH]
                saved = await run_pipeline(batch, db)
                await db.commit()
                total += len(saved)

            logger.info("Scheduler: daily scan complete — %d signals generated", total)
        except Exception as e:
            logger.exception("Scheduler: daily scan failed: %s", e)