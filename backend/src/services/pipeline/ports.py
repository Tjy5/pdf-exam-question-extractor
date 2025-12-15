"""
Pipeline ports - Hexagonal architecture interfaces for external dependencies.

This module defines the boundary interfaces (ports) that decouple the pipeline
core from infrastructure concerns like storage, eventing, and persistence.

Interfaces:
- ArtifactStore: Artifact storage (files, images, etc.)
- EventPublisher: Live event fanout (in-process bus, broker)
- EventStore: Durable event log for SSE replay
- TaskRepository: Task state persistence
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol, Sequence


@dataclass(frozen=True, slots=True)
class StoredEvent:
    """Durable event record for SSE replay and auditing.

    Attributes:
        id: Monotonically increasing event ID (globally or per task_id)
        task_id: Associated task identifier
        event_type: Event type (e.g., 'step_started', 'log', 'done')
        payload: Event payload as a mapping
        created_at_iso: RFC3339/ISO8601 timestamp string (UTC recommended)
    """

    id: int
    task_id: str
    event_type: str
    payload: Mapping[str, Any]
    created_at_iso: str


class ArtifactStore(Protocol):
    """Artifact storage interface.

    Abstracts the storage backend for pipeline artifacts (images, PDFs, etc.).
    The `save` method returns an opaque reference that can be used with `load`,
    allowing the backing store to change (SQLite BLOBs -> filesystem -> S3)
    without modifying pipeline code.
    """

    def save(self, *, task_id: str, step: str, name: str, data: bytes) -> str:
        """Save artifact data and return a reference string."""
        ...

    def load(self, *, ref: str) -> bytes:
        """Load artifact data by reference."""
        ...

    def list(self, *, task_id: str, step: str) -> Sequence[str]:
        """List artifact references for a task/step."""
        ...


class EventPublisher(Protocol):
    """Best-effort live event fanout interface.

    Used for real-time event delivery (in-process bus, Redis pub/sub, etc.).
    Events published here may be lost on failure - use EventStore for durability.
    """

    def publish(self, *, task_id: str, event_type: str, payload: Mapping[str, Any]) -> None:
        """Publish an event for live subscribers."""
        ...


class EventStore(Protocol):
    """Append-only event store for SSE replay and auditing.

    Provides durable event storage with monotonic IDs for Last-Event-ID replay.
    Events are stored per task and can be queried for catch-up streaming.

    Note: Methods are defined as sync but implementations may be async.
    Use AsyncEventStore for explicitly async implementations.
    """

    def append(self, *, task_id: str, event_type: str, payload: Mapping[str, Any]) -> StoredEvent:
        """Append an event and return the stored record with assigned ID."""
        ...

    def list_since(
        self,
        *,
        task_id: str,
        after_id: int,
        limit: int = 500,
    ) -> Sequence[StoredEvent]:
        """List events after the given ID for replay."""
        ...


class AsyncEventStore(Protocol):
    """Async version of EventStore for use with async database drivers."""

    async def append(self, *, task_id: str, event_type: str, payload: Mapping[str, Any]) -> StoredEvent:
        """Append an event and return the stored record with assigned ID."""
        ...

    async def list_since(
        self,
        *,
        task_id: str,
        after_id: int,
        limit: int = 500,
    ) -> Sequence[StoredEvent]:
        """List events after the given ID for replay."""
        ...


class TaskRepository(Protocol):
    """Task persistence interface.

    Abstracts task state storage for the pipeline. Implementations may use
    SQLite, PostgreSQL, or other backends.
    """

    def get(self, *, task_id: str) -> Mapping[str, Any] | None:
        """Get task data by ID, or None if not found."""
        ...

    def update_status(self, *, task_id: str, status: str) -> None:
        """Update task status."""
        ...

    def append_log(self, *, task_id: str, log: Mapping[str, Any]) -> None:
        """Append a log entry to the task."""
        ...


class CompositeEventSink(Protocol):
    """Combined event publisher + store for atomic event handling.

    Implementations should ensure events are both stored durably and
    published for live delivery. This is the recommended interface for
    pipeline event emission.
    """

    def emit(self, *, task_id: str, event_type: str, payload: Mapping[str, Any]) -> StoredEvent:
        """Store and publish an event atomically."""
        ...
