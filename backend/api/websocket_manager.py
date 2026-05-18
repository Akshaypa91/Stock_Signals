"""api/websocket_manager.py — WebSocket broadcast manager."""
import json
import logging
from typing import Any
from fastapi import WebSocket

logger = logging.getLogger(__name__)


class WebSocketManager:
    def __init__(self) -> None:
        self._connections: list[WebSocket] = []

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self._connections.append(ws)
        logger.info("WS client connected (total: %d)", len(self._connections))

    def disconnect(self, ws: WebSocket) -> None:
        self._connections = [c for c in self._connections if c is not ws]
        logger.info("WS client disconnected (total: %d)", len(self._connections))

    async def broadcast(self, data: Any) -> None:
        """Send JSON payload to all connected frontend clients."""
        if not self._connections:
            return
        message = json.dumps(data, default=str)
        dead: list[WebSocket] = []
        for ws in self._connections:
            try:
                await ws.send_text(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)

    @property
    def connection_count(self) -> int:
        return len(self._connections)


# Module-level singleton
ws_manager = WebSocketManager()
