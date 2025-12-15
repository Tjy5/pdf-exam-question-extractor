"""
Event Infrastructure - Unified event emission entry point.

Provides centralized access to event storage and publishing:
- get_event_store(): Shared SQLiteEventStore instance
- get_event_sink(): Shared CompositeEventSinkImpl (store + publish)
- emit_event(): Durable event emission (store first, then publish)
- publish_live_event(): Live-only emission (no persistence, for high-frequency updates)

Design decisions:
- Durable events (log, step status changes, done) are stored in SQLite for SSE replay
- Live-only events (progress updates) skip storage to avoid DB bloat
- Fire-and-forget async emission with fallback to live-only on DB failure
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Mapping

from ...db.connection import get_db_manager
from ...services.events.store import (
    CompositeEventSinkImpl,
    EventBusAdapter,
    SQLiteEventStore,
)
from .event_bus import event_bus

logger = logging.getLogger(__name__)

# Module-level singletons (lazy initialization)
_store: SQLiteEventStore | None = None
_sink: CompositeEventSinkImpl | None = None


def get_event_store() -> SQLiteEventStore:
    """
    Get the shared SQLiteEventStore instance.

    Requires DatabaseManager to be initialized first (via web.main.lifespan).

    Returns:
        SQLiteEventStore instance for direct event queries
    """
    global _store
    if _store is None:
        db = get_db_manager()  # Will raise if not initialized
        _store = SQLiteEventStore(db)
    return _store


def get_event_sink() -> CompositeEventSinkImpl:
    """
    Get the shared CompositeEventSinkImpl instance.

    The sink stores events durably first, then publishes to live subscribers.

    Returns:
        CompositeEventSinkImpl for durable + live event emission
    """
    global _sink
    if _sink is None:
        _sink = CompositeEventSinkImpl(
            get_event_store(),
            EventBusAdapter(event_bus),
        )
    return _sink


def publish_live_event(
    *,
    task_id: str,
    event_type: str,
    payload: Mapping[str, Any],
) -> None:
    """
    Publish a live-only event (no persistence).

    Use for high-frequency updates like progress that don't need replay.

    Args:
        task_id: Target task ID
        event_type: Event type (step, log, done, etc.)
        payload: Event payload data
    """
    # Handle 'done' event specially: frontend expects plain string data
    if event_type == "done":
        status = payload.get("status") or payload.get("value") or ""
        event_bus.publish(task_id, {"type": "done", "data": str(status)})
        return

    event_bus.publish(task_id, {"type": event_type, "data": dict(payload)})


def emit_event(
    *,
    task_id: str,
    event_type: str,
    payload: Mapping[str, Any],
) -> None:
    """
    Emit a durable event (store first, then publish).

    This is fire-and-forget: schedules async storage and returns immediately.
    On storage failure, falls back to live-only publish.

    Use for important events that need SSE replay support:
    - log: Task log entries
    - step: Step status changes (running, completed, failed)
    - done: Task completion/failure

    Args:
        task_id: Target task ID
        event_type: Event type
        payload: Event payload data
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        # No event loop - fall back to live-only
        logger.warning("emit_event called without event loop; using live-only publish")
        publish_live_event(task_id=task_id, event_type=event_type, payload=payload)
        return

    async def _emit_async() -> None:
        try:
            await get_event_sink().emit(
                task_id=task_id,
                event_type=event_type,
                payload=payload,
            )
        except Exception:
            logger.exception(
                "emit_event storage failed for task=%s type=%s; falling back to live-only",
                task_id,
                event_type,
            )
            try:
                publish_live_event(
                    task_id=task_id,
                    event_type=event_type,
                    payload=payload,
                )
            except Exception:
                logger.exception("Live-only publish also failed")

    loop.create_task(_emit_async(), name=f"emit-{task_id}-{event_type}")


def reset_event_infra() -> None:
    """
    Reset module-level singletons (for testing).
    """
    global _store, _sink
    _store = None
    _sink = None
