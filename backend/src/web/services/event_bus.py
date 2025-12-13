"""
Simple in-memory pub/sub for task events (SSE).
"""
import asyncio
from typing import Any, Dict, List


class EventBus:
    """Per-task subscriber queues for SSE streaming."""

    def __init__(self) -> None:
        self._subscribers: Dict[str, List[asyncio.Queue]] = {}
        self._lock = asyncio.Lock()

    async def subscribe(self, task_id: str) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue()
        async with self._lock:
            self._subscribers.setdefault(task_id, []).append(queue)
        return queue

    async def unsubscribe(self, task_id: str, queue: asyncio.Queue) -> None:
        async with self._lock:
            queues = self._subscribers.get(task_id)
            if queues and queue in queues:
                queues.remove(queue)
            if not queues:
                self._subscribers.pop(task_id, None)

    def publish(self, task_id: str, event: Dict[str, Any]) -> None:
        queues = self._subscribers.get(task_id)
        if not queues:
            return
        for queue in list(queues):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                pass


event_bus = EventBus()
