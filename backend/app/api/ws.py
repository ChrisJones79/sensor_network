from __future__ import annotations

import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter(tags=["ws"])


@router.websocket("/ws/live")
async def ws_live(websocket: WebSocket) -> None:
    await websocket.accept()
    bus = websocket.app.state.live_bus
    queue = await bus.subscribe()

    try:
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=5.0)
            except asyncio.TimeoutError:
                event = {"type": "heartbeat"}
            await websocket.send_json(event)
    except WebSocketDisconnect:
        pass
    finally:
        await bus.unsubscribe(queue)
