"""WebSocket log streaming for campaign send/update events."""

from __future__ import annotations

import asyncio
from typing import Any, Dict, Set

from fastapi import WebSocket, WebSocketDisconnect

_active_connections: Set[WebSocket] = set()
_conn_lock = asyncio.Lock()
_main_loop: asyncio.AbstractEventLoop | None = None


def set_main_loop(loop: asyncio.AbstractEventLoop) -> None:
    global _main_loop
    _main_loop = loop


async def websocket_logs(websocket: WebSocket) -> None:
    """Register websocket and keep it alive until disconnect."""
    await websocket.accept()
    async with _conn_lock:
        _active_connections.add(websocket)

    try:
        while True:
            # We don't expect client messages, but receiving keeps the socket alive.
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        async with _conn_lock:
            _active_connections.discard(websocket)


async def broadcast_log(data: Dict[str, Any]) -> None:
    """Broadcast a log payload to all connected clients."""
    async with _conn_lock:
        connections = list(_active_connections)

    for conn in connections:
        try:
            await conn.send_json(data)
        except Exception:
            async with _conn_lock:
                _active_connections.discard(conn)


def broadcast_log_sync(data: Dict[str, Any]) -> None:
    """Thread-safe broadcast helper for sync code paths."""
    if _main_loop is None:
        return
    try:
        asyncio.run_coroutine_threadsafe(broadcast_log(data), _main_loop)
    except Exception:
        # Best-effort: log streaming must never break email sending.
        return

