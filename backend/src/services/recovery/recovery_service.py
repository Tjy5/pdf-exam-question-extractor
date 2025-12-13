"""
Recovery Service - Handles server restart recovery.

This module provides the RecoveryService that:
- Loads unfinished tasks from database on startup
- Resumes interrupted pipelines
- Handles orphaned tasks
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path
from typing import Any, List, Optional

from ..pipeline.contracts import StepStatus, TaskSnapshot, TaskStatus


class RecoveryService:
    """
    Service for recovering tasks after server restart.

    On server startup, this service:
    1. Queries database for non-terminal tasks
    2. Validates task state against filesystem
    3. Resumes or marks tasks appropriately

    Usage:
        recovery = RecoveryService(task_repository)
        unfinished = await recovery.load_unfinished_tasks()

        for snapshot in unfinished:
            await runner.run(snapshot, context)
    """

    def __init__(self, task_repository: Any) -> None:
        """
        Initialize the service.

        Args:
            task_repository: TaskRepository instance for database access
        """
        self._repo = task_repository

    async def load_unfinished_tasks(self) -> List[TaskSnapshot]:
        """
        Load all tasks that were not completed.

        Returns:
            List of TaskSnapshot objects for unfinished tasks
        """
        snapshots: List[TaskSnapshot] = []

        # Query tasks with non-terminal status
        for status in ["pending", "processing"]:
            tasks = await self._repo.list_tasks(status_filter=status, limit=100)

            for task_data in tasks:
                try:
                    snapshot = await self._build_snapshot(task_data["task_id"])
                    if snapshot:
                        snapshots.append(snapshot)
                except Exception:
                    # Skip tasks that can't be loaded
                    pass

        return snapshots

    async def _build_snapshot(self, task_id: str) -> Optional[TaskSnapshot]:
        """
        Build a TaskSnapshot from database data.

        Args:
            task_id: Task identifier

        Returns:
            TaskSnapshot or None if task not found
        """
        task_data = await self._repo.get_task(task_id)
        if not task_data:
            return None

        task_info = task_data["task"]
        steps_data = task_data["steps"]

        # Create snapshot
        snapshot = TaskSnapshot(
            task_id=task_id,
            mode=task_info.get("mode", "auto"),
            status=TaskStatus(task_info.get("status", "pending")),
            current_step=task_info.get("current_step", -1),
            pdf_name=task_info.get("pdf_name", ""),
            file_hash=task_info.get("file_hash"),
            workdir=self._resolve_workdir(task_info.get("exam_dir_name")),
            expected_pages=task_info.get("expected_pages"),
            created_at=datetime.fromisoformat(task_info["created_at"])
            if task_info.get("created_at")
            else datetime.now(),
            updated_at=datetime.fromisoformat(task_info["updated_at"])
            if task_info.get("updated_at")
            else datetime.now(),
            error_message=task_info.get("error_message"),
        )

        # Build step states
        from ..pipeline.contracts import StepName, StepState

        step_definitions = [
            (0, StepName.pdf_to_images, "PDF 转图片"),
            (1, StepName.extract_questions, "题目提取"),
            (2, StepName.analyze_data, "资料分析重组"),
            (3, StepName.compose_long_image, "长图拼接"),
            (4, StepName.collect_results, "结果汇总"),
        ]

        snapshot.steps = []
        for idx, name, title in step_definitions:
            # Find matching step data
            step_data = next(
                (s for s in steps_data if s.get("step_index") == idx), None
            )

            if step_data:
                import json

                artifact_paths = []
                if step_data.get("artifact_json"):
                    try:
                        artifact_paths = json.loads(step_data["artifact_json"])
                    except json.JSONDecodeError:
                        pass

                step_state = StepState(
                    index=idx,
                    name=name,
                    title=title,
                    status=StepStatus(step_data.get("status", "pending")),
                    started_at=datetime.fromisoformat(step_data["started_at"])
                    if step_data.get("started_at")
                    else None,
                    ended_at=datetime.fromisoformat(step_data["ended_at"])
                    if step_data.get("ended_at")
                    else None,
                    artifact_paths=artifact_paths,
                    error_message=step_data.get("error_message"),
                )
            else:
                step_state = StepState(index=idx, name=name, title=title)

            snapshot.steps.append(step_state)

        return snapshot

    def _resolve_workdir(self, exam_dir_name: Optional[str]) -> Optional[str]:
        """Resolve workdir path from exam_dir_name."""
        if not exam_dir_name:
            return None

        # Assume pdf_images is in project root
        # This should be configurable
        base_dir = Path(__file__).parent.parent.parent.parent / "pdf_images"
        workdir = base_dir / exam_dir_name

        if workdir.exists():
            return str(workdir)

        return None

    async def validate_task_state(self, snapshot: TaskSnapshot) -> TaskSnapshot:
        """
        Validate task state against filesystem.

        Checks if artifacts claimed by steps actually exist.
        Updates step status if artifacts are missing.

        Args:
            snapshot: Task snapshot to validate

        Returns:
            Validated (possibly modified) snapshot
        """
        if not snapshot.workdir:
            return snapshot

        workdir = Path(snapshot.workdir)
        if not workdir.exists():
            # Workdir missing - reset all steps
            for step in snapshot.steps:
                step.status = StepStatus.pending
                step.artifact_paths = []
            return snapshot

        # Validate each step's artifacts
        for step in snapshot.steps:
            if step.status != StepStatus.completed:
                continue

            # Check if artifacts exist
            missing = False
            for artifact_path in step.artifact_paths:
                if not Path(artifact_path).exists():
                    missing = True
                    break

            if missing:
                # Reset this step and all following steps
                for s in snapshot.steps[step.index :]:
                    s.status = StepStatus.pending
                    s.artifact_paths = []
                    s.error_message = None
                break

        return snapshot

    async def recover_tasks(
        self,
        runner: Any,
        model_provider: Any,
        auto_resume: bool = True,
    ) -> List[str]:
        """
        Recover and optionally resume unfinished tasks.

        Args:
            runner: PipelineRunner instance
            model_provider: PPStructureProvider instance
            auto_resume: Whether to automatically resume tasks

        Returns:
            List of task IDs that were recovered
        """
        recovered_ids: List[str] = []

        snapshots = await self.load_unfinished_tasks()

        for snapshot in snapshots:
            # Validate state
            snapshot = await self.validate_task_state(snapshot)

            recovered_ids.append(snapshot.task_id)

            if auto_resume and snapshot.status == TaskStatus.processing:
                # Task was interrupted mid-execution
                # Reset current step to pending for retry
                if snapshot.current_step >= 0:
                    step = snapshot.get_step(snapshot.current_step)
                    if step and step.status == StepStatus.running:
                        step.status = StepStatus.pending

                # Resume in background
                # Note: Actual resumption would need proper context
                # This is a placeholder for the integration

        return recovered_ids
