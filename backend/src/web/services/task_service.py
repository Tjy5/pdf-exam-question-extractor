"""
Task Service - Task lifecycle management
"""
import asyncio
import hashlib
import os
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from ..schemas import LogEntry, StepState, StepStatus, TaskStatus
from .event_infra import emit_event, publish_live_event


class Task:
    """Task state container"""

    def __init__(
        self,
        task_id: str,
        pdf_filename: str,
        mode: str = "auto",
        uploads_dir: Optional[Path] = None,
    ):
        self.id = task_id
        self.mode = mode
        self.status: TaskStatus = "pending"
        self.logs: List[LogEntry] = []
        self.current_step = -1
        self.pdf_filename = Path(pdf_filename).name
        self.file_hash: Optional[str] = None
        self.expected_pages: Optional[int] = None
        self.result_images: List[Dict[str, str]] = []
        self.error_message: Optional[str] = None
        self.last_log_index = 0
        self.created_at = datetime.now()
        self.updated_at = datetime.now()

        # File paths
        base_dir = uploads_dir or Path(__file__).parent.parent.parent.parent / "uploads"
        self.uploads_dir = base_dir
        self.uploads_dir.mkdir(parents=True, exist_ok=True)

        self.task_workdir = self.uploads_dir / task_id
        self.task_workdir.mkdir(parents=True, exist_ok=True)

        self.pdf_path = self.task_workdir / self.pdf_filename
        self.exam_dir: Optional[Path] = None

        # Initialize step states (names must match StepName enum in pipeline/contracts.py)
        self.steps: List[StepState] = [
            StepState(index=0, name="pdf_to_images", title="PDF 转图片"),
            StepState(index=1, name="extract_questions", title="题目提取"),
            StepState(index=2, name="analyze_data", title="资料分析重组"),
            StepState(index=3, name="compose_long_image", title="长图拼接"),
            StepState(index=4, name="collect_results", title="结果汇总"),
        ]

        # Live step event throttling (protects SSE/event loop from high-frequency updates)
        self._live_step_emit_last_at: Dict[int, float] = {}
        self._live_step_emit_last_progress: Dict[int, float] = {}

    def add_log(self, message: str, log_type: str = "default", durable: bool = True) -> None:
        """Add a log entry with timestamp and unique ID"""
        now = datetime.now()
        time_str = now.strftime("%H:%M:%S")
        log_id = f"{int(now.timestamp() * 1000)}-{uuid.uuid4().hex[:8]}"
        entry = LogEntry(id=log_id, time=time_str, message=message, type=log_type)
        self.logs.append(entry)
        self.updated_at = now
        self.last_log_index = len(self.logs) - 1
        payload = entry.dict()
        if durable:
            # Durable: log events need SSE replay support
            emit_event(task_id=self.id, event_type="log", payload=payload)
        else:
            # Live-only: avoid SQLite commit storms for high-frequency logs
            publish_live_event(task_id=self.id, event_type="log", payload=payload)

    def get_step(self, step_index: int) -> Optional[StepState]:
        """Get step state by index"""
        if 0 <= step_index < len(self.steps):
            return self.steps[step_index]
        return None

    def mark_step_running(self, step_index: int) -> None:
        """Mark a step as running"""
        step = self.get_step(step_index)
        if step:
            step.status = StepStatus.RUNNING
            step.progress = 0.0
            step.started_at = datetime.now()
            self.current_step = step_index
            self.updated_at = datetime.now()
            self._emit_step_event(durable=True)

    def mark_step_completed(
        self, step_index: int, artifact_paths: Optional[List[str]] = None
    ) -> None:
        """Mark a step as completed"""
        step = self.get_step(step_index)
        if step:
            step.status = StepStatus.COMPLETED
            step.progress = 1.0
            step.ended_at = datetime.now()
            if artifact_paths:
                step.artifact_paths = artifact_paths
            self.updated_at = datetime.now()
            self._emit_step_event(durable=True)

    def mark_step_failed(self, step_index: int, error: str) -> None:
        """Mark a step as failed"""
        step = self.get_step(step_index)
        if step:
            step.status = StepStatus.FAILED
            step.progress = None
            step.ended_at = datetime.now()
            step.error_message = error
            self.updated_at = datetime.now()
            self._emit_step_event(durable=True)

    def update_step_progress(self, step_index: int, progress: float) -> None:
        """Update the progress (0.0-1.0) for a running step"""
        step = self.get_step(step_index)
        if step and step.status == StepStatus.RUNNING:
            step.progress = max(0.0, min(1.0, progress))
            self.updated_at = datetime.now()
            # Live-only: progress updates are high-frequency, skip DB storage
            # Also throttle emission to avoid flooding SSE/event loop.
            try:
                min_interval_ms = int(os.getenv("EXAMPAPER_STEP_PROGRESS_MIN_INTERVAL_MS", "200"))
            except (ValueError, TypeError):
                min_interval_ms = 200
            min_interval_ms = max(0, min_interval_ms)

            try:
                min_delta = float(os.getenv("EXAMPAPER_STEP_PROGRESS_MIN_DELTA", "0.01"))
            except (ValueError, TypeError):
                min_delta = 0.01
            min_delta = max(0.0, min_delta)

            interval_s = max(0.0, float(min_interval_ms) / 1000.0)

            now_m = time.monotonic()
            last_t = float(self._live_step_emit_last_at.get(step_index, 0.0))
            last_p = self._live_step_emit_last_progress.get(step_index)

            cur_p = float(step.progress if step.progress is not None else 0.0)
            force = cur_p <= 0.0 or cur_p >= 1.0

            should_emit = (
                force
                or last_p is None
                or abs(cur_p - float(last_p)) >= min_delta
                or (now_m - last_t) >= interval_s
            )
            if not should_emit:
                return

            self._live_step_emit_last_at[step_index] = now_m
            self._live_step_emit_last_progress[step_index] = cur_p
            self._emit_step_event(durable=False)

    def can_run_step(self, step_index: int) -> tuple[bool, Optional[str]]:
        """Check if a step can be run"""
        if step_index < 0 or step_index >= len(self.steps):
            return False, f"Invalid step index: {step_index}"

        step = self.steps[step_index]

        if step.status == StepStatus.COMPLETED:
            return False, f"步骤 {step.title} 已经完成"

        if step.status == StepStatus.RUNNING:
            return False, f"步骤 {step.title} 正在运行中"

        if step_index > 0 and self.mode != "manual":
            prev_step = self.steps[step_index - 1]
            if prev_step.status not in [StepStatus.COMPLETED, StepStatus.SKIPPED]:
                return False, f"请先完成步骤 {prev_step.title}"

        if self.current_step >= 0 and self.current_step != step_index:
            running_step = self.steps[self.current_step]
            return False, f"步骤 {running_step.title} 正在运行中，请等待完成"

        return True, None

    def reset_step(self, step_index: int) -> None:
        """Reset a step to pending state"""
        step = self.get_step(step_index)
        if step and step.status == StepStatus.FAILED:
            step.status = StepStatus.PENDING
            step.progress = None
            step.error_message = None
            step.started_at = None
            step.ended_at = None
            self.updated_at = datetime.now()
            self._emit_step_event(durable=True)

    def serialize_steps(self) -> List[Dict[str, Any]]:
        """Return a lightweight view used by SSE and status APIs."""
        return [
            {
                "index": step.index,
                "name": step.name,
                "title": step.title,
                "status": step.status.value,
                "progress": step.progress,
                "progress_text": None,
                "artifact_count": len(step.artifact_paths),
                "error": step.error_message,
            }
            for step in self.steps
        ]

    def _emit_step_event(self, *, durable: bool) -> None:
        """
        Publish current step snapshot to SSE listeners.

        Args:
            durable: If True, store in DB for SSE replay (status changes).
                     If False, live-only publish (progress updates).
        """
        payload = {"steps": self.serialize_steps()}
        if durable:
            emit_event(task_id=self.id, event_type="step", payload=payload)
        else:
            publish_live_event(task_id=self.id, event_type="step", payload=payload)


class TaskManager:
    """Manages task storage and locks"""

    def __init__(self):
        self.tasks: Dict[str, Task] = {}
        self.task_locks: Dict[str, asyncio.Lock] = {}
        self.exam_locks: Dict[str, asyncio.Lock] = {}

    def create_task(
        self,
        pdf_filename: str,
        mode: str = "auto",
        uploads_dir: Optional[Path] = None,
    ) -> Task:
        """Create a new task"""
        task_id = uuid.uuid4().hex
        task = Task(task_id, pdf_filename, mode, uploads_dir)
        self.tasks[task_id] = task
        return task

    def get_task(self, task_id: str) -> Optional[Task]:
        """Get task by ID"""
        return self.tasks.get(task_id)

    def get_task_lock(self, task_id: str) -> asyncio.Lock:
        """Get or create a lock for a specific task"""
        if task_id not in self.task_locks:
            self.task_locks[task_id] = asyncio.Lock()
        return self.task_locks[task_id]

    def get_exam_lock(self, exam_key: str) -> asyncio.Lock:
        """Get or create a lock for a specific exam directory"""
        if exam_key not in self.exam_locks:
            self.exam_locks[exam_key] = asyncio.Lock()
        return self.exam_locks[exam_key]


# Global task manager instance
task_manager = TaskManager()
