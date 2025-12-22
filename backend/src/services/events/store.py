"""
Event Store - SQLite implementation for SSE replay.

Implements EventStore and CompositeEventSink ports from services/pipeline/ports.py.
Provides durable event storage with monotonic IDs for Last-Event-ID replay.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Mapping, Sequence

from ..pipeline.ports import EventPublisher, EventStore, StoredEvent


def _now_iso() -> str:
    """Get current UTC timestamp in ISO8601 format."""
    return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%fZ")


class SQLiteEventStore:
    """
    SQLite-backed event store for SSE replay.

    Implements AsyncEventStore protocol from services/pipeline/ports.py.

    Features:
    - Monotonic integer IDs for Last-Event-ID support
    - Efficient replay via indexed queries
    - JSON payload storage

    Usage:
        store = SQLiteEventStore(db_manager)
        event = await store.append(task_id="123", event_type="step", payload={"step": 0})
        events = await store.list_since(task_id="123", after_id=0)
    """

    def __init__(self, db_manager: Any) -> None:
        """
        Initialize with database manager.

        Args:
            db_manager: DatabaseManager instance from db/connection.py
        """
        self._db = db_manager

    async def append(
        self,
        *,
        task_id: str,
        event_type: str,
        payload: Mapping[str, Any],
    ) -> StoredEvent:
        """Append an event and return the stored record with assigned ID."""
        payload_json = json.dumps(payload, ensure_ascii=False)
        created_at = _now_iso()

        async with self._db.transaction():
            cursor = await self._db.execute(
                """
                INSERT INTO task_events (task_id, event_type, payload_json, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (task_id, event_type, payload_json, created_at),
            )
            event_id = cursor.lastrowid

        return StoredEvent(
            id=event_id,
            task_id=task_id,
            event_type=event_type,
            payload=payload,
            created_at_iso=created_at,
        )

    async def list_since(
        self,
        *,
        task_id: str,
        after_id: int,
        limit: int = 500,
    ) -> Sequence[StoredEvent]:
        """List events after the given ID for replay."""
        async with self._db.transaction():
            rows = await self._db.fetch_all(
                """
                SELECT id, task_id, event_type, payload_json, created_at
                FROM task_events
                WHERE task_id = ? AND id > ?
                ORDER BY id ASC
                LIMIT ?
                """,
                (task_id, after_id, limit),
            )

        events = []
        for row in rows:
            try:
                payload = json.loads(row["payload_json"])
            except (json.JSONDecodeError, TypeError):
                payload = {}

            events.append(
                StoredEvent(
                    id=row["id"],
                    task_id=row["task_id"],
                    event_type=row["event_type"],
                    payload=payload,
                    created_at_iso=row["created_at"],
                )
            )

        return events

    async def get_latest_id(self, *, task_id: str) -> int:
        """Get the latest event ID for a task (0 if no events)."""
        async with self._db.transaction():
            row = await self._db.fetch_one(
                """
                SELECT MAX(id) as max_id FROM task_events WHERE task_id = ?
                """,
                (task_id,),
            )
        return row["max_id"] if row and row["max_id"] else 0

    async def delete_for_task(self, *, task_id: str) -> int:
        """Delete all events for a task. Returns count deleted."""
        async with self._db.transaction():
            cursor = await self._db.execute(
                "DELETE FROM task_events WHERE task_id = ?",
                (task_id,),
            )
            rowcount = cursor.rowcount
        return rowcount


class CompositeEventSinkImpl:
    """
    Composite event sink that stores and publishes events.

    Implements the CompositeEventSink port: stores event durably first,
    then publishes for live delivery.

    Usage:
        sink = CompositeEventSinkImpl(event_store, event_bus)
        event = await sink.emit(task_id="123", event_type="step", payload={...})
    """

    def __init__(
        self,
        event_store: SQLiteEventStore,
        event_publisher: EventPublisher,
    ) -> None:
        self._store = event_store
        self._publisher = event_publisher

    async def emit(
        self,
        *,
        task_id: str,
        event_type: str,
        payload: Mapping[str, Any],
    ) -> StoredEvent:
        """Store and publish an event atomically."""
        # Store first (durable)
        event = await self._store.append(
            task_id=task_id,
            event_type=event_type,
            payload=payload,
        )

        # Then publish (best-effort)
        try:
            # Include event ID in published payload for client deduplication
            publish_payload = dict(payload)
            publish_payload["_event_id"] = event.id
            self._publisher.publish(
                task_id=task_id,
                event_type=event_type,
                payload=publish_payload,
            )
        except Exception:
            # Don't fail if publish fails - event is already stored
            pass

        return event


class EventBusAdapter:
    """
    Adapter to make existing EventBus compatible with EventPublisher port.

    Bridges the gap between the existing event_bus.publish(task_id, event_dict)
    and the EventPublisher.publish(task_id, event_type, payload) interface.

    Special handling for 'done' events:
    - Frontend expects data to be a plain string ("completed" or "error")
    - Event ID is placed at top level for SSE handler extraction
    """

    def __init__(self, event_bus: Any) -> None:
        self._bus = event_bus

    def publish(
        self,
        *,
        task_id: str,
        event_type: str,
        payload: Mapping[str, Any],
    ) -> None:
        """Publish event via the underlying event bus."""
        event_id = payload.get("_event_id")

        # Handle 'done' event specially: frontend expects plain string data
        if event_type == "done":
            status = payload.get("status") or payload.get("value") or ""
            self._bus.publish(
                task_id,
                {"type": "done", "data": str(status), "_event_id": event_id},
            )
            return

        # Standard event: include _event_id at top level for SSE handler
        event_data = {"type": event_type, "data": dict(payload)}
        if event_id is not None:
            event_data["_event_id"] = event_id
        self._bus.publish(task_id, event_data)
