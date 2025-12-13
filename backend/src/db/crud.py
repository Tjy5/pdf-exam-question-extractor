"""
CRUD operations for task persistence.

Provides TaskRepository for:
- Creating and retrieving tasks
- Updating task/step status
- Managing logs
- Querying task history
"""

import json
from typing import Optional, List, Dict, Any
from pathlib import Path

from .connection import DatabaseManager
from .schema import (
    TaskRecord,
    StepRecord,
    LogRecord,
    TaskStatus,
    StepStatus,
    TaskMode,
    LogType,
    now_iso8601,
)


class TaskRepository:
    """
    Repository for task persistence operations.

    Encapsulates all database interactions for tasks, steps, and logs.
    """

    def __init__(self, db: DatabaseManager):
        """
        Initialize repository.

        Args:
            db: DatabaseManager instance
        """
        self.db = db

    # ==================== Task Operations ====================

    async def create_task(
        self,
        task_id: str,
        mode: str,
        pdf_name: str,
        file_hash: Optional[str] = None,
        exam_dir_name: Optional[str] = None,
        expected_pages: Optional[int] = None,
    ) -> str:
        """
        Create a new task with initial steps.

        Args:
            task_id: Unique task identifier
            mode: Execution mode ('auto' or 'manual')
            pdf_name: Original PDF filename
            file_hash: SHA256 hash of PDF content
            exam_dir_name: Relative exam directory name
            expected_pages: Number of pages in PDF

        Returns:
            Created task_id
        """
        now = now_iso8601()

        async with self.db.transaction():
            # Insert task
            await self.db.execute(
                """
                INSERT INTO tasks (
                    task_id, mode, pdf_name, file_hash, exam_dir_name,
                    status, expected_pages, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (task_id, mode, pdf_name, file_hash, exam_dir_name, "pending", expected_pages, now, now),
            )

            # Initialize 5 steps (matching Task.__init__ in app.py)
            steps = [
                (task_id, 0, "pdf_to_images", "PDF 转图片"),
                (task_id, 1, "extract_questions", "题目提取"),
                (task_id, 2, "data_analysis", "资料分析重组"),
                (task_id, 3, "compose_long_images", "长图拼接"),
                (task_id, 4, "collect_results", "结果汇总"),
            ]

            await self.db.execute_many(
                """
                INSERT INTO task_steps (task_id, step_index, name, title, status)
                VALUES (?, ?, ?, ?, 'pending')
                """,
                steps,
            )

        return task_id

    async def get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        """
        Get task by ID with all steps and recent logs.

        Args:
            task_id: Task identifier

        Returns:
            Dict with 'task', 'steps', 'logs' keys, or None if not found
        """
        async with self.db.transaction():
            # Fetch task
            task_row = await self.db.fetch_one(
                "SELECT * FROM tasks WHERE task_id = ? AND deleted_at IS NULL",
                (task_id,),
            )

            if not task_row:
                return None

            # Fetch steps
            step_rows = await self.db.fetch_all(
                """
                SELECT * FROM task_steps
                WHERE task_id = ?
                ORDER BY step_index
                """,
                (task_id,),
            )

            # Fetch recent logs (last 100)
            log_rows = await self.db.fetch_all(
                """
                SELECT * FROM task_logs
                WHERE task_id = ?
                ORDER BY id DESC
                LIMIT 100
                """,
                (task_id,),
            )

            return {
                "task": dict(task_row),
                "steps": [dict(row) for row in step_rows],
                "logs": [dict(row) for row in reversed(log_rows)],  # Chronological order
            }

    async def list_tasks(
        self,
        status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """
        List tasks with optional status filter.

        Args:
            status: Filter by status (None = all)
            limit: Maximum number of tasks
            offset: Pagination offset

        Returns:
            List of task dicts (without steps/logs for performance)
        """
        async with self.db.transaction():
            if status:
                rows = await self.db.fetch_all(
                    """
                    SELECT * FROM tasks
                    WHERE status = ? AND deleted_at IS NULL
                    ORDER BY created_at DESC
                    LIMIT ? OFFSET ?
                    """,
                    (status, limit, offset),
                )
            else:
                rows = await self.db.fetch_all(
                    """
                    SELECT * FROM tasks
                    WHERE deleted_at IS NULL
                    ORDER BY created_at DESC
                    LIMIT ? OFFSET ?
                    """,
                    (limit, offset),
                )

            return [dict(row) for row in rows]

    async def find_task_by_hash(self, file_hash: str) -> Optional[Dict[str, Any]]:
        """
        Find most recent non-deleted task with given file hash.

        Args:
            file_hash: PDF SHA256 hash

        Returns:
            Task dict or None
        """
        async with self.db.transaction():
            row = await self.db.fetch_one(
                """
                SELECT * FROM tasks
                WHERE file_hash = ? AND deleted_at IS NULL
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (file_hash,),
            )
            return dict(row) if row else None

    async def update_task_status(
        self,
        task_id: str,
        status: str,
        current_step: Optional[int] = None,
        error_message: Optional[str] = None,
    ):
        """
        Update task status and current step.

        Args:
            task_id: Task identifier
            status: New status
            current_step: Current step index (-1 = not started)
            error_message: Error message (if failed)
        """
        now = now_iso8601()
        finished_at = now if status in ("completed", "failed") else None

        async with self.db.transaction():
            if current_step is not None:
                await self.db.execute(
                    """
                    UPDATE tasks
                    SET status = ?, current_step = ?, error_message = ?,
                        updated_at = ?, finished_at = ?
                    WHERE task_id = ?
                    """,
                    (status, current_step, error_message, now, finished_at, task_id),
                )
            else:
                await self.db.execute(
                    """
                    UPDATE tasks
                    SET status = ?, error_message = ?, updated_at = ?, finished_at = ?
                    WHERE task_id = ?
                    """,
                    (status, error_message, now, finished_at, task_id),
                )

    async def delete_task(self, task_id: str, soft: bool = True):
        """
        Delete task (soft or hard).

        Args:
            task_id: Task identifier
            soft: If True, set deleted_at; if False, hard delete with CASCADE
        """
        async with self.db.transaction():
            if soft:
                await self.db.execute(
                    "UPDATE tasks SET deleted_at = ? WHERE task_id = ?",
                    (now_iso8601(), task_id),
                )
            else:
                # Hard delete (cascades to steps and logs via FK)
                await self.db.execute(
                    "DELETE FROM tasks WHERE task_id = ?",
                    (task_id,),
                )

    # ==================== Step Operations ====================

    async def update_step_status(
        self,
        task_id: str,
        step_index: int,
        status: str,
        error_message: Optional[str] = None,
        artifact_paths: Optional[List[str]] = None,
    ):
        """
        Update step status.

        Args:
            task_id: Task identifier
            step_index: Step index (0-4)
            status: New status
            error_message: Error message (if failed)
            artifact_paths: List of artifact file paths (None = no update, [] = clear)
        """
        now = now_iso8601()

        # Determine timestamps based on status transition
        started_at = now if status == "running" else None
        ended_at = now if status in ("completed", "failed", "skipped") else None

        # Fix: Use "is not None" check instead of truthiness to allow empty list
        artifact_json = json.dumps(artifact_paths) if artifact_paths is not None else None

        async with self.db.transaction():
            # Update step (preserving existing timestamps if not transitioning)
            await self.db.execute(
                """
                UPDATE task_steps
                SET status = ?,
                    error_message = ?,
                    started_at = COALESCE(?, started_at),
                    ended_at = COALESCE(?, ended_at),
                    artifact_json = COALESCE(?, artifact_json)
                WHERE task_id = ? AND step_index = ?
                """,
                (status, error_message, started_at, ended_at, artifact_json, task_id, step_index),
            )

            # Also update tasks.updated_at
            await self.db.execute(
                "UPDATE tasks SET updated_at = ? WHERE task_id = ?",
                (now, task_id),
            )

    async def get_step(self, task_id: str, step_index: int) -> Optional[Dict[str, Any]]:
        """
        Get step by task_id and step_index.

        Args:
            task_id: Task identifier
            step_index: Step index (0-4)

        Returns:
            Step dict or None
        """
        async with self.db.transaction():
            row = await self.db.fetch_one(
                """
                SELECT * FROM task_steps
                WHERE task_id = ? AND step_index = ?
                """,
                (task_id, step_index),
            )
            return dict(row) if row else None

    # ==================== Log Operations ====================

    async def add_log(
        self,
        task_id: str,
        message: str,
        log_type: str = "default",
    ):
        """
        Add a log entry.

        Args:
            task_id: Task identifier
            message: Log message
            log_type: Log type ('default', 'info', 'success', 'error')
        """
        now = now_iso8601()

        async with self.db.transaction():
            await self.db.execute(
                """
                INSERT INTO task_logs (task_id, type, message, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (task_id, log_type, message, now),
            )

            # Update tasks.updated_at
            await self.db.execute(
                "UPDATE tasks SET updated_at = ? WHERE task_id = ?",
                (now, task_id),
            )

    async def get_logs(
        self,
        task_id: str,
        since_id: Optional[int] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """
        Get logs for a task, optionally since a specific log ID.

        Args:
            task_id: Task identifier
            since_id: Return logs with id > since_id (for polling)
            limit: Maximum number of logs

        Returns:
            List of log dicts
        """
        async with self.db.transaction():
            if since_id is not None:
                rows = await self.db.fetch_all(
                    """
                    SELECT * FROM task_logs
                    WHERE task_id = ? AND id > ?
                    ORDER BY id
                    LIMIT ?
                    """,
                    (task_id, since_id, limit),
                )
            else:
                rows = await self.db.fetch_all(
                    """
                    SELECT * FROM task_logs
                    WHERE task_id = ?
                    ORDER BY id DESC
                    LIMIT ?
                    """,
                    (task_id, limit),
                )
                rows = list(reversed(rows))  # Chronological order

            return [dict(row) for row in rows]
