"""
Database connection manager for SQLite.

Provides:
- Async SQLite connection management using aiosqlite
- Concurrent access protection via transaction-scoped locks
- Transaction support with automatic commit/rollback
- Schema initialization
"""

import asyncio
import aiosqlite
import logging
import warnings
from pathlib import Path
from typing import Optional
from contextlib import asynccontextmanager

from .schema import SCHEMA_SQL

logger = logging.getLogger(__name__)


class DatabaseManager:
    """
    Manages SQLite database connections with async support.

    Features:
    - Lazy initialization
    - Single shared connection with transaction-level locking
    - Schema auto-initialization
    - Transaction management with automatic commit/rollback

    Note: Uses a global lock to prevent transaction interleaving on the shared connection.
    This is appropriate for low-concurrency workloads (<10 concurrent requests).
    """

    def __init__(self, db_path: Path):
        """
        Initialize database manager.

        Args:
            db_path: Path to SQLite database file
        """
        self.db_path = db_path
        self._connection: Optional[aiosqlite.Connection] = None
        self._initialized = False

        # Prevent multi-statement transaction interleaving on shared connection
        self._lock = asyncio.Lock()

        # Prevent concurrent init() calls
        self._init_lock = asyncio.Lock()

        # Track active transaction owner to prevent interleaving/reentrancy
        self._transaction_owner: Optional[asyncio.Task] = None

    async def init(self):
        """
        Initialize database connection and schema.

        - Creates database file if not exists
        - Executes schema SQL (idempotent via CREATE IF NOT EXISTS)
        - Sets up PRAGMAs for optimal web app performance

        Thread-safe: Can be called multiple times, only initializes once.
        """
        if self._initialized:
            return

        async with self._init_lock:
            # Double-check after acquiring lock
            if self._initialized:
                return

            try:
                # Ensure parent directory exists
                self.db_path.parent.mkdir(parents=True, exist_ok=True)

                # Create connection
                self._connection = await aiosqlite.connect(
                    str(self.db_path),
                    timeout=5.0,
                )

                # Enable row factory for dict-like access
                self._connection.row_factory = aiosqlite.Row

                # Execute schema (PRAGMAs + CREATE TABLE + indexes + triggers)
                await self._connection.executescript(SCHEMA_SQL)
                await self._apply_migrations()
                await self._connection.commit()

                self._initialized = True

            except Exception:
                # Cleanup on failure to prevent connection leak
                if self._connection:
                    await self._connection.close()
                    self._connection = None
                raise

    async def _apply_migrations(self) -> None:
        """
        Best-effort runtime migrations for existing DB files.
        We avoid a full migration framework and only apply additive changes.
        """
        await self._ensure_column("exam_questions", "image_data", "TEXT")
        await self._ensure_wrong_notebook_schema()

    async def _table_exists(self, table: str) -> bool:
        """Check if a table exists in the SQLite schema."""
        if not self._connection:
            return False
        cursor = await self._connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name = ?",
            (table,),
        )
        try:
            row = await cursor.fetchone()
        finally:
            await cursor.close()
        return row is not None

    async def _ensure_column(self, table: str, column: str, column_def: str) -> None:
        """
        Add a column if missing.
        NOTE: SQLite doesn't support ALTER TABLE ... ADD COLUMN IF NOT EXISTS,
        so we probe PRAGMA table_info first.
        Handles multi-process race conditions by ignoring "duplicate column" errors.
        """
        if not self._connection:
            return

        if not await self._table_exists(table):
            return

        cursor = await self._connection.execute(f"PRAGMA table_info({table})")
        try:
            rows = await cursor.fetchall()
        finally:
            await cursor.close()
        existing = {str(r["name"]) for r in rows}
        if column in existing:
            return

        try:
            await self._connection.execute(
                f"ALTER TABLE {table} ADD COLUMN {column} {column_def}"
            )
        except Exception as e:
            # Ignore "duplicate column name" error from race condition
            err_msg = str(e).lower()
            if "duplicate column" not in err_msg:
                raise

    async def _ensure_wrong_notebook_schema(self) -> None:
        """
        Ensure wrong-notebook related tables/columns exist.
        Applies additive changes only; safe for existing databases.
        """
        if not self._connection:
            return

        # Create missing tables (idempotent)
        await self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT UNIQUE NOT NULL,
                display_name TEXT DEFAULT '学员',
                created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
                last_active_at TEXT
            )
            """
        )
        await self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS user_wrong_questions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                source_type TEXT DEFAULT 'exam' CHECK (source_type IN ('exam', 'upload')),
                exam_id INTEGER,
                question_no INTEGER,
                user_answer TEXT,
                original_image TEXT,
                ai_question_text TEXT,
                ai_answer_text TEXT,
                ai_analysis TEXT,
                subject TEXT,
                source_name TEXT,
                error_type TEXT,
                user_notes TEXT,
                status TEXT DEFAULT 'wrong',
                mastery_level INTEGER DEFAULT 0 CHECK (mastery_level BETWEEN 0 AND 2),
                marked_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
                updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
                UNIQUE(user_id, exam_id, question_no),
                FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
                FOREIGN KEY (exam_id) REFERENCES exams(id) ON DELETE CASCADE
            )
            """
        )
        await self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS knowledge_tags (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                subject TEXT NOT NULL,
                parent_id TEXT,
                is_system INTEGER DEFAULT 0,
                user_id TEXT,
                sort_order INTEGER DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
                FOREIGN KEY (parent_id) REFERENCES knowledge_tags(id) ON DELETE CASCADE,
                FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
                UNIQUE(subject, name, user_id)
            )
            """
        )
        await self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS wrong_question_tags (
                wrong_question_id INTEGER NOT NULL,
                tag_id TEXT NOT NULL,
                PRIMARY KEY (wrong_question_id, tag_id),
                FOREIGN KEY (wrong_question_id) REFERENCES user_wrong_questions(id) ON DELETE CASCADE,
                FOREIGN KEY (tag_id) REFERENCES knowledge_tags(id) ON DELETE CASCADE
            )
            """
        )

        # Ensure missing columns for existing tables
        await self._ensure_column("users", "display_name", "TEXT DEFAULT '学员'")
        await self._ensure_column(
            "users",
            "created_at",
            "TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))",
        )
        await self._ensure_column("users", "last_active_at", "TEXT")

        await self._ensure_column(
            "user_wrong_questions",
            "source_type",
            "TEXT DEFAULT 'exam' CHECK (source_type IN ('exam', 'upload'))",
        )
        await self._ensure_column("user_wrong_questions", "exam_id", "INTEGER")
        await self._ensure_column("user_wrong_questions", "question_no", "INTEGER")
        await self._ensure_column("user_wrong_questions", "user_answer", "TEXT")
        await self._ensure_column("user_wrong_questions", "original_image", "TEXT")
        await self._ensure_column("user_wrong_questions", "ai_question_text", "TEXT")
        await self._ensure_column("user_wrong_questions", "ai_answer_text", "TEXT")
        await self._ensure_column("user_wrong_questions", "ai_analysis", "TEXT")
        await self._ensure_column("user_wrong_questions", "subject", "TEXT")
        await self._ensure_column("user_wrong_questions", "source_name", "TEXT")
        await self._ensure_column("user_wrong_questions", "error_type", "TEXT")
        await self._ensure_column("user_wrong_questions", "user_notes", "TEXT")
        await self._ensure_column("user_wrong_questions", "status", "TEXT DEFAULT 'wrong'")
        await self._ensure_column(
            "user_wrong_questions",
            "mastery_level",
            "INTEGER DEFAULT 0 CHECK (mastery_level BETWEEN 0 AND 2)",
        )
        await self._ensure_column(
            "user_wrong_questions",
            "marked_at",
            "TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))",
        )
        await self._ensure_column(
            "user_wrong_questions",
            "updated_at",
            "TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))",
        )

        await self._ensure_column("knowledge_tags", "name", "TEXT NOT NULL")
        await self._ensure_column("knowledge_tags", "subject", "TEXT NOT NULL")
        await self._ensure_column("knowledge_tags", "parent_id", "TEXT")
        await self._ensure_column("knowledge_tags", "is_system", "INTEGER DEFAULT 0")
        await self._ensure_column("knowledge_tags", "user_id", "TEXT")
        await self._ensure_column("knowledge_tags", "sort_order", "INTEGER DEFAULT 0")
        await self._ensure_column(
            "knowledge_tags",
            "created_at",
            "TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))",
        )

        await self._ensure_column("wrong_question_tags", "wrong_question_id", "INTEGER NOT NULL")
        await self._ensure_column("wrong_question_tags", "tag_id", "TEXT NOT NULL")

    async def close(self):
        """
        Close database connection.

        Note: Acquires lock to ensure no in-flight transactions.
        Should only be called during application shutdown.
        """
        async with self._lock:
            if self._connection:
                await self._connection.close()
                self._connection = None
                self._initialized = False

    @property
    def connection(self) -> aiosqlite.Connection:
        """
        Get the active connection.

        Raises:
            RuntimeError: If database not initialized
        """
        if not self._initialized or not self._connection:
            raise RuntimeError("Database not initialized. Call init() first.")
        return self._connection

    def _warn_outside_transaction(self, operation: str, reason: str) -> None:
        message = (
            f"{operation} called outside of transaction(): {reason}. "
            "Use 'async with db.transaction()' to ensure isolation."
        )
        warnings.warn(message, RuntimeWarning, stacklevel=3)
        logger.warning(message)

    def _require_transaction(self, operation: str) -> None:
        current_task = asyncio.current_task()
        owner = self._transaction_owner
        if owner is None:
            self._warn_outside_transaction(operation, "no active transaction")
            raise RuntimeError(
                f"{operation} requires an active transaction. "
                "Use 'async with db.transaction()'."
            )
        if owner is not current_task:
            self._warn_outside_transaction(
                operation, "transaction owned by a different task"
            )
            raise RuntimeError(
                f"{operation} must run within the current task's transaction. "
                "Use 'async with db.transaction()' in this task."
            )

    async def execute(self, sql: str, parameters=None) -> aiosqlite.Cursor:
        """
        Execute a single SQL statement.

        Args:
            sql: SQL statement
            parameters: Query parameters (tuple or dict)

        Returns:
            Cursor object
        """
        self._require_transaction("execute")
        return await self.connection.execute(sql, parameters or ())

    async def execute_many(self, sql: str, parameters_list):
        """
        Execute a SQL statement multiple times with different parameters.

        Args:
            sql: SQL statement
            parameters_list: List of parameter tuples
        """
        self._require_transaction("execute_many")
        await self.connection.executemany(sql, parameters_list)

    async def fetch_one(self, sql: str, parameters=None) -> Optional[aiosqlite.Row]:
        """
        Execute query and fetch one row.

        Args:
            sql: SELECT query
            parameters: Query parameters

        Returns:
            Row object or None
        """
        self._require_transaction("fetch_one")
        cursor = await self.execute(sql, parameters)
        try:
            return await cursor.fetchone()
        finally:
            await cursor.close()

    async def fetch_all(self, sql: str, parameters=None) -> list[aiosqlite.Row]:
        """
        Execute query and fetch all rows.

        Args:
            sql: SELECT query
            parameters: Query parameters

        Returns:
            List of row objects
        """
        self._require_transaction("fetch_all")
        cursor = await self.execute(sql, parameters)
        try:
            return await cursor.fetchall()
        finally:
            await cursor.close()

    async def commit(self):
        """Commit current transaction."""
        await self.connection.commit()

    async def rollback(self):
        """Rollback current transaction."""
        await self.connection.rollback()

    @asynccontextmanager
    async def transaction(self):
        """
        Async context manager for transactions with locking.

        Usage:
            async with db.transaction():
                await db.execute("INSERT INTO ...")
                await db.execute("UPDATE ...")
                # Auto-commits on success, rolls back on exception

        Note: Acquires global lock to prevent transaction interleaving.
        All Repository methods should use this to ensure atomicity.

        **IMPORTANT**: Do NOT nest transactions. asyncio.Lock is not reentrant.
        Calling transaction() inside another transaction() will deadlock.
        Repository methods should not call other repository methods directly.
        """
        current_task = asyncio.current_task()
        if self._transaction_owner is current_task:
            self._warn_outside_transaction(
                "transaction()", "nested transaction in the same task"
            )
            raise RuntimeError("Nested transaction() is not allowed.")

        async with self._lock:
            if self._transaction_owner is not None:
                self._warn_outside_transaction(
                    "transaction()", "transaction already active in another task"
                )
                raise RuntimeError("Another transaction is already active.")
            self._transaction_owner = current_task
            try:
                await self.connection.execute("BEGIN TRANSACTION")
                try:
                    yield self
                except Exception:
                    await self.rollback()
                    raise
                else:
                    await self.commit()
            finally:
                self._transaction_owner = None


# ==================== Global Instance ====================

_db_manager: Optional[DatabaseManager] = None


def get_db_manager(db_path: Optional[Path] = None) -> DatabaseManager:
    """
    Get or create the global DatabaseManager instance.

    Args:
        db_path: Path to database file (required on first call)

    Returns:
        DatabaseManager instance

    Raises:
        ValueError: If db_path not provided on first call
    """
    global _db_manager

    if _db_manager is None:
        if db_path is None:
            raise ValueError("db_path required for first call to get_db_manager()")
        _db_manager = DatabaseManager(db_path)

    return _db_manager


def reset_db_manager():
    """Reset global DatabaseManager instance (mainly for testing)."""
    global _db_manager
    _db_manager = None
