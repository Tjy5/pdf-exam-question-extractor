"""
Simple in-memory pub/sub for task events (SSE).
"""
import asyncio
import logging
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

# Bounded queue size to prevent unbounded memory growth with slow consumers
# Adjust based on event frequency and acceptable backlog
DEFAULT_QUEUE_MAXSIZE = 1000


class EventBus:
    """Per-task subscriber queues for SSE streaming with bounded memory."""

    def __init__(self) -> None:
        self._subscribers: Dict[str, List[asyncio.Queue]] = {}
        self._lock = asyncio.Lock()

    async def subscribe(self, task_id: str) -> asyncio.Queue:
        """
        Subscribe to events for a task.
        Returns a bounded queue to prevent memory leaks from slow consumers.
        """
        # Use bounded queue to protect against slow/stuck consumers
        queue: asyncio.Queue = asyncio.Queue(maxsize=DEFAULT_QUEUE_MAXSIZE)
        async with self._lock:
            self._subscribers.setdefault(task_id, []).append(queue)
            subscriber_count = len(self._subscribers[task_id])

        logger.info(
            f"EventBus: New subscriber for task {task_id} "
            f"(total: {subscriber_count}, queue_maxsize: {DEFAULT_QUEUE_MAXSIZE})"
        )
        return queue

    async def unsubscribe(self, task_id: str, queue: asyncio.Queue) -> None:
        """Remove a subscriber queue and cleanup if no subscribers remain."""
        async with self._lock:
            queues = self._subscribers.get(task_id)
            if queues and queue in queues:
                queues.remove(queue)
            if not queues:
                self._subscribers.pop(task_id, None)

            remaining = len(self._subscribers.get(task_id, []))

        logger.info(f"EventBus: Unsubscribed from task {task_id} (remaining: {remaining})")

    def publish(self, task_id: str, event: Dict[str, Any]) -> None:
        """
        Publish event to all subscribers of a task.
        Handles slow consumers gracefully by dropping events and logging warnings.
        """
        queues = self._subscribers.get(task_id)
        if not queues:
            return

        # Iterate over a copy to allow safe removal during iteration
        for queue in list(queues):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                # Slow consumer: queue backlog reached limit
                # Strategy: Drop oldest event to make room for latest state
                logger.warning(
                    f"EventBus: Queue full for task {task_id}, "
                    f"dropping oldest event (slow consumer detected)"
                )
                try:
                    # Remove oldest event to make room
                    queue.get_nowait()
                    # Try putting the new event again
                    queue.put_nowait(event)
                except asyncio.QueueEmpty:
                    # Edge case: another coroutine drained the queue
                    try:
                        queue.put_nowait(event)
                    except asyncio.QueueFull:
                        # Still full, drop this event
                        logger.warning(
                            f"EventBus: Still full after cleanup for task {task_id}, "
                            f"dropping current event"
                        )
                except asyncio.QueueFull:
                    # Still full after dropping oldest, skip this event
                    logger.warning(
                        f"EventBus: Unable to enqueue event for task {task_id} "
                        f"after dropping oldest, consumer too slow"
                    )
            except Exception as e:
                # Unexpected error - log and continue to other subscribers
                logger.error(
                    f"EventBus: Error publishing to subscriber for task {task_id}: {e}",
                    exc_info=True
                )


event_bus = EventBus()
