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

-- Task events for SSE replay (append-only)
CREATE TABLE IF NOT EXISTS task_events (
    id INTEGER PRIMARY KEY,  -- Monotonic ID for Last-Event-ID
    task_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
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
CREATE INDEX IF NOT EXISTS idx_events_task_id_id
    ON task_events(task_id, id);

-- ==================== AI Chat Feature Tables ====================
-- These tables support exam browsing, answer import, wrong question marking, and AI chat

-- Exams table (links to tasks for processing history)
CREATE TABLE IF NOT EXISTS exams (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT UNIQUE,
    exam_dir_name TEXT UNIQUE NOT NULL,
    display_name TEXT,
    file_hash TEXT,
    question_count INTEGER DEFAULT 0,
    has_answers INTEGER DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    processed_at TEXT,
    FOREIGN KEY (task_id) REFERENCES tasks(task_id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_exams_task_id ON exams(task_id);
CREATE INDEX IF NOT EXISTS idx_exams_created_at ON exams(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_exams_file_hash ON exams(file_hash) WHERE file_hash IS NOT NULL;

-- Exam questions table
CREATE TABLE IF NOT EXISTS exam_questions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    exam_id INTEGER NOT NULL,
    question_no INTEGER NOT NULL,
    question_type TEXT DEFAULT 'single',
    image_filename TEXT NOT NULL,
    image_data TEXT,
    ocr_text TEXT,
    meta_json TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE(exam_id, question_no),
    FOREIGN KEY (exam_id) REFERENCES exams(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_exam_questions_exam_id ON exam_questions(exam_id, question_no);

-- Standard answers table
CREATE TABLE IF NOT EXISTS exam_answers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    exam_id INTEGER NOT NULL,
    question_no INTEGER NOT NULL,
    answer TEXT NOT NULL,
    source TEXT DEFAULT 'manual',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE(exam_id, question_no),
    FOREIGN KEY (exam_id) REFERENCES exams(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_exam_answers_exam_id ON exam_answers(exam_id);

-- Users table
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT UNIQUE NOT NULL,
    display_name TEXT DEFAULT '学员',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    last_active_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_users_user_id ON users(user_id);

-- User wrong questions table (supports exam source and independent upload)
CREATE TABLE IF NOT EXISTS user_wrong_questions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,

    -- Source type: 'exam' (from exam marking) or 'upload' (independent upload)
    source_type TEXT DEFAULT 'exam' CHECK (source_type IN ('exam', 'upload')),

    -- Exam source fields (used when source_type='exam')
    exam_id INTEGER,
    question_no INTEGER,
    user_answer TEXT,

    -- Upload source field (used when source_type='upload')
    original_image TEXT,           -- Base64 encoded image

    -- AI analysis results (shared by both sources)
    ai_question_text TEXT,         -- AI parsed question text (Markdown + LaTeX)
    ai_answer_text TEXT,           -- AI generated answer
    ai_analysis TEXT,              -- AI analysis steps

    -- Metadata
    subject TEXT,                  -- Subject: 数学/物理/化学/生物/英语/语文/其他
    source_name TEXT,              -- Source name: 期中考试/周测 etc.
    error_type TEXT,               -- Error type: 计算错误/概念错误/审题错误/方法错误
    user_notes TEXT,               -- User notes

    -- Status
    status TEXT DEFAULT 'wrong',
    mastery_level INTEGER DEFAULT 0 CHECK (mastery_level BETWEEN 0 AND 2),

    -- Timestamps
    marked_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),

    -- Unique constraint only for exam source
    UNIQUE(user_id, exam_id, question_no),
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
    FOREIGN KEY (exam_id) REFERENCES exams(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_wrong_user_exam ON user_wrong_questions(user_id, exam_id);
CREATE INDEX IF NOT EXISTS idx_wrong_user_source ON user_wrong_questions(user_id, source_type);
CREATE INDEX IF NOT EXISTS idx_wrong_mastery ON user_wrong_questions(mastery_level);
CREATE INDEX IF NOT EXISTS idx_wrong_subject ON user_wrong_questions(subject);
CREATE INDEX IF NOT EXISTS idx_wrong_updated ON user_wrong_questions(updated_at DESC);

-- Knowledge tags table (hierarchical with adjacency list)
CREATE TABLE IF NOT EXISTS knowledge_tags (
    id TEXT PRIMARY KEY,                    -- UUID
    name TEXT NOT NULL,                     -- Tag name: 勾股定理
    subject TEXT NOT NULL,                  -- Subject: math/physics/chemistry/biology/english/chinese/other

    -- Hierarchy (adjacency list)
    parent_id TEXT,                         -- Parent tag ID

    -- Classification
    is_system INTEGER DEFAULT 0,            -- 1=system preset, 0=user custom
    user_id TEXT,                           -- User ID for custom tags

    -- Sorting
    sort_order INTEGER DEFAULT 0,

    -- Timestamps
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),

    -- Foreign keys
    FOREIGN KEY (parent_id) REFERENCES knowledge_tags(id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,

    -- Unique constraint: same name under same subject for same user (or system)
    UNIQUE(subject, name, user_id)
);

CREATE INDEX IF NOT EXISTS idx_tags_subject ON knowledge_tags(subject);
CREATE INDEX IF NOT EXISTS idx_tags_parent ON knowledge_tags(parent_id);
CREATE INDEX IF NOT EXISTS idx_tags_user ON knowledge_tags(user_id);
CREATE INDEX IF NOT EXISTS idx_tags_system ON knowledge_tags(is_system);

-- Wrong question to tag association table (many-to-many)
CREATE TABLE IF NOT EXISTS wrong_question_tags (
    wrong_question_id INTEGER NOT NULL,
    tag_id TEXT NOT NULL,
    PRIMARY KEY (wrong_question_id, tag_id),
    FOREIGN KEY (wrong_question_id) REFERENCES user_wrong_questions(id) ON DELETE CASCADE,
    FOREIGN KEY (tag_id) REFERENCES knowledge_tags(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_wqt_question ON wrong_question_tags(wrong_question_id);
CREATE INDEX IF NOT EXISTS idx_wqt_tag ON wrong_question_tags(tag_id);

-- Chat sessions table
CREATE TABLE IF NOT EXISTS chat_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT UNIQUE NOT NULL,
    user_id TEXT NOT NULL,
    exam_id INTEGER NOT NULL,
    question_no INTEGER NOT NULL,
    title TEXT,
    provider TEXT DEFAULT 'openai_compatible',
    model TEXT,
    settings_json TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    last_message_at TEXT,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
    FOREIGN KEY (exam_id) REFERENCES exams(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_chat_sessions_user ON chat_sessions(user_id, last_message_at DESC);
CREATE INDEX IF NOT EXISTS idx_chat_sessions_question ON chat_sessions(exam_id, question_no);

-- Chat messages table
CREATE TABLE IF NOT EXISTS chat_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('system', 'user', 'assistant', 'tool')),
    content TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    provider TEXT,
    model TEXT,
    request_id TEXT,
    usage_json TEXT,
    FOREIGN KEY (session_id) REFERENCES chat_sessions(session_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_chat_messages_session ON chat_messages(session_id, id);

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
