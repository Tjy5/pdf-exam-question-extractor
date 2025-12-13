"""
Web API Schemas - Pydantic models for request/response
"""
from datetime import datetime
from enum import Enum
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel


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
    artifact_paths: List[str] = []
    error_message: Optional[str] = None


class TaskResponse(BaseModel):
    task_id: str
    filename: str
    mode: str
    steps: List[dict]


class StatusResponse(BaseModel):
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
    task_id: str
