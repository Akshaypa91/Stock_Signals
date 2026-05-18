"""
backend/main.py
===============
FastAPI application entry point.

Starts: PostgreSQL, Redis, Upstox realtime feed, all API routers, WebSocket endpoint.
"""

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from database import init_db, close_db
from redis_client import init_redis, close_redis
from upstox.auth import router as auth_router
from upstox.realtime import feed as realtime_feed
from engine.data_fetch import on_ltp_update
from api.webhook import router as webhook_router
from api.stocks import router as signals_router
from api.trades import router as trades_router
from api.scanner import router as scanner_router
from api.websocket_manager import ws_manager

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Lifespan: startup + shutdown
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("=== Investors Way starting up ===")

    # 1. Redis
    await init_redis()

    # 2. Database (create tables)
    await init_db()

    # 3. Start Upstox realtime feed
    realtime_feed.register_callback(on_ltp_update)
    await realtime_feed.start()

    logger.info("=== All services ready ===")
    yield

    # --- Shutdown ---
    logger.info("=== Shutting down ===")
    await realtime_feed.stop()
    await close_db()
    await close_redis()
    logger.info("=== Shutdown complete ===")


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Investors Way",
    description="Indian equity trading signal dashboard — Upstox + Chartink",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS — allow React dev server and production domain
ALLOWED_ORIGINS = os.getenv(
    "ALLOWED_ORIGINS",
    "http://localhost:3000,http://localhost:5173,https://yourdomain.com",
).split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------
app.include_router(auth_router)
app.include_router(webhook_router)
app.include_router(signals_router)
app.include_router(trades_router)
app.include_router(scanner_router)


# ---------------------------------------------------------------------------
# WebSocket endpoint
# ---------------------------------------------------------------------------

@app.websocket("/ws/signals")
async def ws_signals(websocket: WebSocket):
    """
    Persistent WebSocket for the React dashboard.
    Broadcasts:
      - type: "new_signals" — new signals from Chartink/scanner
      - type: "ltp"         — live price updates
      - type: "status_update" — signal status changed (SL/T1/T2 hit)
    """
    await ws_manager.connect(websocket)
    try:
        # Send a welcome / current stats ping
        await websocket.send_json({
            "type": "connected",
            "message": "Investors Way signal feed connected",
            "subscribed_instruments": len(realtime_feed._subscribed),
        })
        # Keep connection alive — client pings, we pong
        while True:
            try:
                msg = await websocket.receive_text()
                if msg == "ping":
                    await websocket.send_text("pong")
            except WebSocketDisconnect:
                break
    except WebSocketDisconnect:
        pass
    finally:
        ws_manager.disconnect(websocket)


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

@app.get("/health", tags=["system"])
async def health() -> dict:
    from redis_client import get_redis
    redis = await get_redis()
    await redis.ping()
    return {
        "status": "ok",
        "ws_clients": ws_manager.connection_count,
        "feed_connected": realtime_feed.is_connected,
        "subscribed": len(realtime_feed._subscribed),
    }


@app.get("/", tags=["system"])
async def root() -> dict:
    return {"app": "Investors Way", "docs": "/docs"}
