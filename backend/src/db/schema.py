"""
Database schema definitions for task persistence.

Uses SQLite with:
- TEXT timestamps (ISO8601 format, UTC)
- CHECK constraints for data integrity
- Foreign key cascades for cleanup
- Optimized indexes for common queries
"""

from enum import Enum
from typing import Optional, List
from datetime import datetime
from pydantic import BaseModel


# ==================== Enums ====================

class TaskStatus(str, Enum):
    """Task execution status."""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class StepStatus(str, Enum):
    """Step execution status."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class LogType(str, Enum):
    """Log entry type."""
    DEFAULT = "default"
    INFO = "info"
    SUCCESS = "success"
    ERROR = "error"


class TaskMode(str, Enum):
    """Task execution mode."""
    AUTO = "auto"
    MANUAL = "manual"


# ==================== Pydantic Models ====================

class TaskRecord(BaseModel):
    """Task database record."""
    task_id: str
    mode: str  # TaskMode enum value
    pdf_name: str
    file_hash: Optional[str] = None
    exam_dir_name: Optional[str] = None  # Relative directory name, not absolute path
    status: str  # TaskStatus enum value
    current_step: int = -1  # -1 means not started
    error_message: Optional[str] = None
    expected_pages: Optional[int] = None
    created_at: str  # ISO8601 timestamp
    updated_at: str  # ISO8601 timestamp
    finished_at: Optional[str] = None  # ISO8601 timestamp
    deleted_at: Optional[str] = None  # For soft-delete, if needed

    class Config:
        from_attributes = True


class StepRecord(BaseModel):
    """Task step database record."""
    task_id: str
    step_index: int  # 0-4
    name: str  # Internal name (e.g., "pdf_to_images")
    title: str  # Display name (e.g., "PDF 转图片")
    status: str  # StepStatus enum value
    error_message: Optional[str] = None
    started_at: Optional[str] = None  # ISO8601 timestamp
    ended_at: Optional[str] = None  # ISO8601 timestamp
    artifact_json: Optional[str] = None  # JSON-encoded list of artifact paths

    class Config:
        from_attributes = True


class LogRecord(BaseModel):
    """Task log database record."""
    id: Optional[int] = None  # Auto-increment primary key
    task_id: str
    created_at: str  # ISO8601 timestamp
    type: str  # LogType enum value
    message: str

    class Config:
        from_attributes = True


# ==================== SQL DDL ====================

# SQLite schema (based on codex review feedback)
SCHEMA_SQL = """
-- Enable foreign keys and optimize for web app workload
PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
PRAGMA busy_timeout = 5000;

-- Main task table
CREATE TABLE IF NOT EXISTS tasks (
    task_id TEXT PRIMARY KEY,
    mode TEXT NOT NULL CHECK (mode IN ('auto', 'manual')),
    pdf_name TEXT NOT NULL,
    file_hash TEXT,
    exam_dir_name TEXT,  -- Relative directory name (e.g., "exam_name__12345678")
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'processing', 'completed', 'failed')),
    current_step INTEGER NOT NULL DEFAULT -1
        CHECK (current_step BETWEEN -1 AND 4),
    error_message TEXT,
    expected_pages INTEGER,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    finished_at TEXT,
    deleted_at TEXT
);

-- Task steps (5 steps per task: 0-4)
CREATE TABLE IF NOT EXISTS task_steps (
    task_id TEXT NOT NULL,
    step_index INTEGER NOT NULL CHECK (step_index BETWEEN 0 AND 4),
    name TEXT NOT NULL,  -- Internal name
    title TEXT NOT NULL,  -- Display name
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'running', 'completed', 'failed', 'skipped')),
    error_message TEXT,
    started_at TEXT,
    ended_at TEXT,
    artifact_json TEXT,  -- JSON array of paths, e.g., ["path1", "path2"]
    PRIMARY KEY (task_id, step_index),
    FOREIGN KEY (task_id) REFERENCES tasks(task_id) ON DELETE CASCADE
) WITHOUT ROWID;

-- Task logs (append-only)
CREATE TABLE IF NOT EXISTS task_logs (
    id INTEGER PRIMARY KEY,  -- No AUTOINCREMENT for performance
    task_id TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    type TEXT NOT NULL CHECK (type IN ('default', 'info', 'success', 'error')),
    message TEXT NOT NULL,
    FOREIGN KEY (task_id) REFERENCES tasks(task_id) ON DELETE CASCADE
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_tasks_status_created_at
    ON tasks(status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_tasks_created_at
    ON tasks(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_tasks_hash
    ON tasks(file_hash) WHERE file_hash IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_logs_task_id_id
    ON task_logs(task_id, id);

-- Trigger to auto-update tasks.updated_at on UPDATE
CREATE TRIGGER IF NOT EXISTS update_tasks_timestamp
AFTER UPDATE ON tasks
FOR EACH ROW
WHEN NEW.updated_at = OLD.updated_at  -- Only if not manually set
BEGIN
    UPDATE tasks SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
    WHERE task_id = NEW.task_id;
END;
"""


# ==================== Helper Functions ====================

def now_iso8601() -> str:
    """Get current UTC timestamp in ISO8601 format."""
    return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def parse_iso8601(timestamp: str) -> datetime:
    """Parse ISO8601 timestamp to datetime."""
    return datetime.strptime(timestamp, "%Y-%m-%dT%H:%M:%S.%fZ")


def format_iso8601(dt: datetime) -> str:
    """Format datetime to ISO8601 string."""
    return dt.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
