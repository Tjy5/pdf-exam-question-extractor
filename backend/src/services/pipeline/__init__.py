"""
Pipeline module - Processing pipeline for exam paper extraction.

This module provides the core pipeline infrastructure:
- contracts: Data models and protocols
- steps: Individual step executors
- runner: Pipeline orchestration
"""

from .contracts import (
    FatalError,
    LogCallback,
    RetryableError,
    StepContext,
    StepName,
    StepResult,
    StepState,
    StepStatus,
    TaskSnapshot,
    TaskStatus,
)
from .ports import (
    ArtifactStore,
    AsyncEventStore,
    CompositeEventSink,
    EventPublisher,
    EventStore,
    StoredEvent,
    TaskRepository,
)
from .registry import StepRegistry, register_default_steps
from .runner import PipelineRunner

__all__ = [
    # Enums
    "StepName",
    "TaskStatus",
    "StepStatus",
    # Models
    "StepContext",
    "StepResult",
    "StepState",
    "TaskSnapshot",
    # Types
    "LogCallback",
    # Exceptions
    "RetryableError",
    "FatalError",
    # Runner
    "PipelineRunner",
    # Ports (interfaces)
    "ArtifactStore",
    "AsyncEventStore",
    "EventPublisher",
    "EventStore",
    "StoredEvent",
    "TaskRepository",
    "CompositeEventSink",
    # Registry
    "StepRegistry",
    "register_default_steps",
]
