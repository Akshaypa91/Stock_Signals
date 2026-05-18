"""
redis_client.py
===============
Async Redis client using redis-py with connection pooling.
Single shared pool for the entire app lifetime.
"""

import logging
import os
from typing import Optional

import redis.asyncio as aioredis

logger = logging.getLogger(__name__)

_redis_client: Optional[aioredis.Redis] = None


async def init_redis() -> None:
    """Call once during app startup (main.py lifespan)."""
    global _redis_client
    url = os.environ.get("REDIS_URL", "redis://localhost:6379")
    _redis_client = aioredis.from_url(
        url,
        encoding="utf-8",
        decode_responses=True,     # always str, not bytes
        max_connections=20,
        socket_keepalive=True,
        socket_connect_timeout=5,
        retry_on_timeout=True,
    )
    # Verify connection
    await _redis_client.ping()
    logger.info("Redis connected: %s", url)


async def close_redis() -> None:
    """Call during app shutdown."""
    global _redis_client
    if _redis_client:
        await _redis_client.aclose()
        _redis_client = None
        logger.info("Redis connection closed")


async def get_redis() -> aioredis.Redis:
    """Return the shared Redis client. Raises if not initialised."""
    if _redis_client is None:
        raise RuntimeError("Redis not initialised — call init_redis() first")
    return _redis_client
