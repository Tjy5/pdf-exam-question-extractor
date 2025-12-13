"""
Database module for task persistence.

Provides SQLite-based storage for:
- Task metadata and status
- Step execution states
- Processing logs
- Historical task records

Usage:
    from backend.src.db import get_db_manager, Task, TaskStep

    db = get_db_manager()
    await db.init()

    # Create task
    task_id = await db.create_task(...)

    # Query tasks
    tasks = await db.list_tasks()
"""

from .connection import DatabaseManager, get_db_manager
from .crud import TaskRepository
from .schema import (
    TaskStatus,
    StepStatus,
    TaskRecord,
    StepRecord,
    LogRecord,
)

__all__ = [
    # Connection
    "DatabaseManager",
    "get_db_manager",
    # Repository
    "TaskRepository",
    # Models
    "TaskStatus",
    "StepStatus",
    "TaskRecord",
    "StepRecord",
    "LogRecord",
]
