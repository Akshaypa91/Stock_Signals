"""
database.py
===========
Async SQLAlchemy engine + session factory for PostgreSQL.
Uses asyncpg driver (postgresql+asyncpg://...).
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

# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------
_raw_url = os.environ.get(
    "DATABASE_URL",
    "postgresql://user:password@localhost:5432/investorsway",
)

# Convert standard postgresql:// → asyncpg driver URL
DATABASE_URL = _raw_url.replace(
    "postgresql://", "postgresql+asyncpg://"
).replace(
    "postgres://", "postgresql+asyncpg://"
)

engine: AsyncEngine = create_async_engine(
    DATABASE_URL,
    echo=False,           # set True for SQL debug logging
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,   # detect stale connections
    pool_recycle=3600,    # recycle connections every hour
)

# ---------------------------------------------------------------------------
# Session factory
# ---------------------------------------------------------------------------
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=True,
    autocommit=False,
)


# ---------------------------------------------------------------------------
# Base class for all ORM models
# ---------------------------------------------------------------------------
class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------------------
# Dependency for FastAPI routes
# ---------------------------------------------------------------------------
async def get_db() -> AsyncSession:
    """
    FastAPI dependency that yields an async DB session.

    Usage in route:
        async def my_route(db: AsyncSession = Depends(get_db)):
            ...
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


# ---------------------------------------------------------------------------
# Init helper called from main.py lifespan
# ---------------------------------------------------------------------------
async def init_db() -> None:
    """Create all tables if they don't exist, and apply incremental migrations."""
    from models import signal, trade  # noqa: F401 — registers models
    async with engine.begin() as conn:
        # Create any missing tables (idempotent)
        await conn.run_sync(Base.metadata.create_all)

        # Migration: add sl_label column (Indian market SL quality: Good/OK/Wide)
        await conn.execute(text(
            "ALTER TABLE signals ADD COLUMN IF NOT EXISTS sl_label VARCHAR(20)"
        ))

        # Migration: add timeframe column (Weekly (NSE) / Daily (NSE))
        await conn.execute(text(
            "ALTER TABLE signals ADD COLUMN IF NOT EXISTS timeframe VARCHAR(20)"
        ))

        # Backfill sl_label for any existing rows that don't have it yet
        await conn.execute(text("""
            UPDATE signals
            SET sl_label = CASE
                WHEN sl_pct <= 8  THEN 'Good'
                WHEN sl_pct <= 12 THEN 'OK'
                ELSE 'Wide — Skip'
            END
            WHERE sl_label IS NULL AND sl_pct IS NOT NULL
        """))

        # Backfill timeframe for existing rows (all were daily scans)
        await conn.execute(text("""
            UPDATE signals
            SET timeframe = 'Daily (NSE)'
            WHERE timeframe IS NULL
        """))

    logger.info("Database tables initialised and migrations applied")


async def close_db() -> None:
    await engine.dispose()
    logger.info("Database connections closed")