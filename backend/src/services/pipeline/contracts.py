"""
Pipeline contracts - Data models, enums, and protocols for the processing pipeline.

This module defines the core abstractions used throughout the pipeline:
- StepName: Enum of all processing steps
- TaskStatus/StepStatus: Status enums
- StepContext: Input context for step execution
- StepResult: Output result from step execution
- TaskSnapshot: Complete task state snapshot
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from pydantic import BaseModel, Field


class StepName(str, Enum):
    """Names of all processing steps in the pipeline."""

    pdf_to_images = "pdf_to_images"
    extract_questions = "extract_questions"
    analyze_data = "analyze_data"
    compose_long_image = "compose_long_image"
    collect_results = "collect_results"


class TaskStatus(str, Enum):
    """Overall task status."""

    pending = "pending"
    processing = "processing"
    completed = "completed"
    failed = "failed"


class StepStatus(str, Enum):
    """Individual step status."""

    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"
    skipped = "skipped"


# Type alias for logging callback
LogCallback = Callable[[str, str], None]  # (message, level)


class StepContext(BaseModel):
    """
    Context passed to each step executor.

    Attributes:
        task_id: Unique task identifier
        pdf_path: Path to the uploaded PDF file
        workdir: Working directory for this task (exam_dir)
        file_hash: SHA256 hash of the PDF content
        expected_pages: Number of pages in the PDF
        metadata: Additional metadata from previous steps
        log: Callback for logging messages
    """

    task_id: str
    pdf_path: str
    workdir: str
    file_hash: Optional[str] = None
    expected_pages: Optional[int] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

    class Config:
        arbitrary_types_allowed = True


class StepResult(BaseModel):
    """
    Result returned by a step executor.

    Attributes:
        name: Name of the step that produced this result
        success: Whether the step completed successfully
        output_path: Path to the output (usually same as workdir)
        artifact_paths: List of paths to generated artifacts
        artifact_count: Number of artifacts generated
        metrics: Performance metrics (e.g., processing time)
        error: Error message if step failed
        can_retry: Whether the error is retryable
    """

    name: StepName
    success: bool
    output_path: Optional[str] = None
    artifact_paths: List[str] = Field(default_factory=list)
    artifact_count: int = 0
    metrics: Dict[str, float] = Field(default_factory=dict)
    error: Optional[str] = None
    can_retry: bool = True


class StepState(BaseModel):
    """
    State of a single step within a task.

    Attributes:
        index: Step index (0-4)
        name: Step name enum
        title: Human-readable title
        status: Current status
        progress: Execution progress (0.0-1.0), None if not started
        started_at: When the step started
        ended_at: When the step ended
        artifact_paths: Paths to generated artifacts
        error_message: Error message if failed
        retry_count: Number of retry attempts
    """

    index: int
    name: StepName
    title: str
    status: StepStatus = StepStatus.pending
    progress: Optional[float] = None
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None
    artifact_paths: List[str] = Field(default_factory=list)
    error_message: Optional[str] = None
    retry_count: int = 0


class TaskSnapshot(BaseModel):
    """
    Complete snapshot of a task's state.

    This is the primary data structure for task state management,
    used for persistence, recovery, and API responses.

    Attributes:
        task_id: Unique task identifier
        mode: Execution mode ('auto' or 'manual')
        status: Overall task status
        current_step: Index of currently running step (-1 if none)
        pdf_name: Original PDF filename
        file_hash: SHA256 hash of PDF content
        workdir: Working directory path
        expected_pages: Number of pages in PDF
        steps: List of step states
        created_at: Task creation timestamp
        updated_at: Last update timestamp
        error_message: Overall error message if failed
    """

    task_id: str
    mode: str = "auto"
    status: TaskStatus = TaskStatus.pending
    current_step: int = -1
    pdf_name: str = ""
    file_hash: Optional[str] = None
    workdir: Optional[str] = None
    expected_pages: Optional[int] = None
    steps: List[StepState] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    error_message: Optional[str] = None

    @classmethod
    def create_new(
        cls,
        task_id: str,
        pdf_name: str,
        mode: str = "auto",
        file_hash: Optional[str] = None,
        workdir: Optional[str] = None,
        expected_pages: Optional[int] = None,
    ) -> "TaskSnapshot":
        """Create a new task snapshot with default step states."""
        step_definitions = [
            (0, StepName.pdf_to_images, "PDF 转图片"),
            (1, StepName.extract_questions, "OCR 识别"),
            (2, StepName.analyze_data, "结构检测"),
            (3, StepName.compose_long_image, "裁剪拼接"),
            (4, StepName.collect_results, "结果汇总"),
        ]

        steps = [
            StepState(index=idx, name=name, title=title)
            for idx, name, title in step_definitions
        ]

        return cls(
            task_id=task_id,
            mode=mode,
            pdf_name=pdf_name,
            file_hash=file_hash,
            workdir=workdir,
            expected_pages=expected_pages,
            steps=steps,
        )

    def get_step(self, index: int) -> Optional[StepState]:
        """Get step state by index."""
        if 0 <= index < len(self.steps):
            return self.steps[index]
        return None

    def get_step_by_name(self, name: StepName) -> Optional[StepState]:
        """Get step state by name."""
        for step in self.steps:
            if step.name == name:
                return step
        return None

    def is_terminal(self) -> bool:
        """Check if task is in a terminal state."""
        return self.status in [TaskStatus.completed, TaskStatus.failed]

    def next_pending_step(self) -> Optional[int]:
        """Get index of next pending step, or None if all done."""
        for step in self.steps:
            if step.status == StepStatus.pending:
                return step.index
        return None


class RetryableError(Exception):
    """Error that can be retried with exponential backoff."""

    pass


class FatalError(Exception):
    """Error that should not be retried."""

    pass
