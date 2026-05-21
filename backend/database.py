"""
database.py
===========
Async SQLAlchemy engine + session factory for PostgreSQL.
"""

import logging
import os

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

logger = logging.getLogger(__name__)

_raw_url = os.environ.get(
    "DATABASE_URL",
    "postgresql://user:password@localhost:5432/investorsway",
)

DATABASE_URL = _raw_url.replace(
    "postgresql://", "postgresql+asyncpg://"
).replace(
    "postgres://", "postgresql+asyncpg://"
)

engine: AsyncEngine = create_async_engine(
    DATABASE_URL,
    echo=False,
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,
    pool_recycle=3600,
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=True,
    autocommit=False,
)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def init_db() -> None:
    """Create tables + apply incremental migrations on every startup."""
    from models import signal, trade  # noqa: F401

    async with engine.begin() as conn:
        # Create missing tables
        await conn.run_sync(Base.metadata.create_all)

        # Migration: add sl_label column
        await conn.execute(text(
            "ALTER TABLE signals ADD COLUMN IF NOT EXISTS sl_label VARCHAR(20)"
        ))

        # Migration: add timeframe column
        await conn.execute(text(
            "ALTER TABLE signals ADD COLUMN IF NOT EXISTS timeframe VARCHAR(20)"
        ))

        # Backfill sl_label for existing rows
        await conn.execute(text("""
            UPDATE signals
            SET sl_label = CASE
                WHEN sl_pct <= 8  THEN 'Good'
                WHEN sl_pct <= 12 THEN 'OK'
                ELSE 'Wide — Skip'
            END
            WHERE sl_label IS NULL AND sl_pct IS NOT NULL
        """))

        # Backfill timeframe for existing rows
        await conn.execute(text("""
            UPDATE signals
            SET timeframe = 'Daily (NSE)'
            WHERE timeframe IS NULL
        """))

        # Migration: add unique constraint to prevent duplicate signals
        # (symbol + strategy + signal_date must be unique)
        await conn.execute(text("""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_constraint
                    WHERE conname = 'uq_signal_symbol_strategy_date'
                ) THEN
                    -- First remove existing duplicates keeping lowest id
                    DELETE FROM signals
                    WHERE id NOT IN (
                        SELECT MIN(id)
                        FROM signals
                        GROUP BY symbol, strategy, signal_date
                    );
                    -- Then add unique constraint
                    ALTER TABLE signals
                    ADD CONSTRAINT uq_signal_symbol_strategy_date
                    UNIQUE (symbol, strategy, signal_date);
                END IF;
            END $$;
        """))

    logger.info("Database tables initialised and migrations applied")


async def close_db() -> None:
    await engine.dispose()
    logger.info("Database connections closed")