"""
Web API Schemas - Pydantic models for request/response
"""
from datetime import datetime
from enum import Enum
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field


TaskStatus = Literal["pending", "processing", "completed", "failed"]


class StepStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class LogEntry(BaseModel):
    id: str
    time: str
    message: str
    type: Literal["default", "info", "success", "error"]


class StepState(BaseModel):
    index: int
    name: str
    title: str
    status: StepStatus = StepStatus.PENDING
    progress: Optional[float] = None
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None
    artifact_paths: List[str] = Field(default_factory=list)
    error_message: Optional[str] = None


class TaskResponse(BaseModel):
    task_id: str
    filename: str
    mode: str
    steps: List[dict]


class StatusResponse(BaseModel):
    task_id: str
    status: TaskStatus
    mode: str
    current_step: int
    steps: List[dict]
    logs: List[dict]
    total_logs: int
    error: Optional[str] = None


class UploadRequest(BaseModel):
    mode: str = "auto"


class ProcessRequest(BaseModel):
    """Request to start processing a task."""
    task_id: str = Field(..., min_length=1, description="Task ID to process")


class StartStepRequest(BaseModel):
    """Request to start a specific step."""
    run_to_end: bool = Field(
        default=False,
        description="If True, run from this step to the end"
    )


class RestartFromStepRequest(BaseModel):
    """Request to restart from a specific step."""
    pass  # No additional fields needed, step index is in path
