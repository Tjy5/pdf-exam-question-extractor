"""
Task Queue - Ports and in-memory implementation.

Provides abstractions for task queue to enable API/Worker separation.
Current: InMemoryTaskQueue for single-process development
Future: RedisTaskQueue for production multi-worker deployment
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Protocol, Sequence


@dataclass(frozen=True)
class QueueItem:
    """Represents a queued task item."""

    id: str
    task_id: str
    attempt: int
    enqueued_at: float
    payload: dict = field(default_factory=dict)
    lease_token: str | None = None  # Set when claimed, required for ack/nack


class TaskQueue(Protocol):
    """
    Task queue port for API/Worker separation.

    Methods:
    - enqueue: Add a task to the queue
    - claim: Worker claims tasks for processing
    - ack: Acknowledge successful completion
    - nack: Return task to queue for retry
    """

    def enqueue(self, *, task_id: str, payload: dict | None = None) -> QueueItem:
        """Add a task to the queue."""
        ...

    def claim(
        self,
        *,
        worker_id: str,
        lease_seconds: int = 60,
        limit: int = 1,
    ) -> Sequence[QueueItem]:
        """Claim tasks for processing with a lease."""
        ...

    def ack(self, *, item_id: str, lease_token: str) -> bool:
        """Acknowledge successful task completion. Returns False if token invalid."""
        ...

    def nack(self, *, item_id: str, lease_token: str, retry_in_seconds: int = 5) -> bool:
        """Return task to queue for retry. Returns False if token invalid."""
        ...

    def size(self) -> int:
        """Get number of items in queue (available + delayed)."""
        ...


class InMemoryTaskQueue:
    """
    In-memory task queue for development and testing.

    Features:
    - FIFO ordering
    - Lease-based claiming with tokens
    - Delayed retry support
    - No persistence (lost on restart)

    Limitations:
    - Single-process only
    - No durability
    - No distributed coordination

    For production, use RedisTaskQueue (to be implemented).
    """

    def __init__(self) -> None:
        self._available: list[QueueItem] = []
        # id -> (item, worker_id, lease_until, lease_token)
        self._inflight: dict[str, tuple[QueueItem, str, float, str]] = {}
        self._delayed: list[tuple[float, QueueItem]] = []  # (ready_at, item)

    def enqueue(self, *, task_id: str, payload: dict | None = None) -> QueueItem:
        """Add a task to the queue."""
        item = QueueItem(
            id=str(uuid.uuid4()),
            task_id=task_id,
            attempt=0,
            enqueued_at=time.time(),
            payload=payload or {},
        )
        self._available.append(item)
        return item

    def claim(
        self,
        *,
        worker_id: str,
        lease_seconds: int = 60,
        limit: int = 1,
    ) -> Sequence[QueueItem]:
        """Claim tasks for processing."""
        now = time.time()

        # Move ready delayed items to available
        ready: list[QueueItem] = []
        still_delayed: list[tuple[float, QueueItem]] = []
        for ready_at, item in self._delayed:
            if ready_at <= now:
                ready.append(item)
            else:
                still_delayed.append((ready_at, item))
        self._delayed = still_delayed
        self._available.extend(ready)

        # Reclaim expired leases
        expired_ids = [
            item_id
            for item_id, (_, _, lease_until, _) in self._inflight.items()
            if lease_until <= now
        ]
        for item_id in expired_ids:
            item, _, _, _ = self._inflight.pop(item_id)
            # Re-enqueue with new ID and incremented attempt
            retry_item = QueueItem(
                id=str(uuid.uuid4()),
                task_id=item.task_id,
                attempt=item.attempt + 1,
                enqueued_at=item.enqueued_at,
                payload=item.payload,
            )
            self._available.append(retry_item)

        # Claim items
        claimed: list[QueueItem] = []
        while self._available and len(claimed) < limit:
            item = self._available.pop(0)
            lease_until = now + float(lease_seconds)
            lease_token = str(uuid.uuid4())
            # Create claimed item with lease_token
            claimed_item = QueueItem(
                id=item.id,
                task_id=item.task_id,
                attempt=item.attempt,
                enqueued_at=item.enqueued_at,
                payload=item.payload,
                lease_token=lease_token,
            )
            self._inflight[item.id] = (claimed_item, worker_id, lease_until, lease_token)
            claimed.append(claimed_item)

        return claimed

    def ack(self, *, item_id: str, lease_token: str) -> bool:
        """Acknowledge successful completion. Returns False if token invalid."""
        entry = self._inflight.get(item_id)
        if not entry:
            return False

        _, _, _, stored_token = entry
        if stored_token != lease_token:
            return False  # Stale ack from previous lease

        self._inflight.pop(item_id, None)
        return True

    def nack(self, *, item_id: str, lease_token: str, retry_in_seconds: int = 5) -> bool:
        """Return task to queue for retry. Returns False if token invalid."""
        entry = self._inflight.get(item_id)
        if not entry:
            return False

        item, _, _, stored_token = entry
        if stored_token != lease_token:
            return False  # Stale nack from previous lease

        self._inflight.pop(item_id, None)
        retry_item = QueueItem(
            id=str(uuid.uuid4()),  # New ID for retry
            task_id=item.task_id,
            attempt=item.attempt + 1,
            enqueued_at=item.enqueued_at,
            payload=item.payload,
        )
        self._delayed.append((time.time() + float(retry_in_seconds), retry_item))
        return True

    def size(self) -> int:
        """Get total queue size."""
        return len(self._available) + len(self._delayed)

    def pending_count(self) -> int:
        """Get number of items being processed."""
        return len(self._inflight)

    def clear(self) -> None:
        """Clear all items (for testing)."""
        self._available.clear()
        self._inflight.clear()
        self._delayed.clear()
