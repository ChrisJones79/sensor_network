from __future__ import annotations

import asyncio
from typing import Any


class LiveEventBus:
    def __init__(self) -> None:
        self._queues: set[asyncio.Queue[dict[str, Any]]] = set()
        self._lock = asyncio.Lock()

    async def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=512)
        async with self._lock:
            self._queues.add(queue)
        return queue

    async def unsubscribe(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        async with self._lock:
            self._queues.discard(queue)

    async def broadcast(self, event: dict[str, Any]) -> None:
        async with self._lock:
            queues = list(self._queues)
        for queue in queues:
            if queue.full():
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                continue
