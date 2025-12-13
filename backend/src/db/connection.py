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
from pathlib import Path
from typing import Optional
from contextlib import asynccontextmanager

from .schema import SCHEMA_SQL


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
                await self._connection.commit()

                self._initialized = True

            except Exception:
                # Cleanup on failure to prevent connection leak
                if self._connection:
                    await self._connection.close()
                    self._connection = None
                raise

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

    async def execute(self, sql: str, parameters=None) -> aiosqlite.Cursor:
        """
        Execute a single SQL statement.

        Args:
            sql: SQL statement
            parameters: Query parameters (tuple or dict)

        Returns:
            Cursor object
        """
        return await self.connection.execute(sql, parameters or ())

    async def execute_many(self, sql: str, parameters_list):
        """
        Execute a SQL statement multiple times with different parameters.

        Args:
            sql: SQL statement
            parameters_list: List of parameter tuples
        """
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
        cursor = await self.execute(sql, parameters)
        return await cursor.fetchone()

    async def fetch_all(self, sql: str, parameters=None) -> list[aiosqlite.Row]:
        """
        Execute query and fetch all rows.

        Args:
            sql: SELECT query
            parameters: Query parameters

        Returns:
            List of row objects
        """
        cursor = await self.execute(sql, parameters)
        return await cursor.fetchall()

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
        async with self._lock:
            try:
                yield self
                await self.commit()
            except Exception:
                await self.rollback()
                raise


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
