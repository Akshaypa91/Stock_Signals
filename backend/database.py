"""
database.py
===========
Async SQLAlchemy engine + session factory for PostgreSQL.
Uses asyncpg driver (postgresql+asyncpg://...).
"""

import logging
import os

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
    """Create all tables if they don't exist (idempotent)."""
    from models import signal, trade  # noqa: F401 — registers models
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database tables initialised")


async def close_db() -> None:
    await engine.dispose()
    logger.info("Database connections closed")
