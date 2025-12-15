"""
Database abstraction layer - Protocols and utilities for database portability.

This module provides:
- DatabaseConnection protocol for type-safe database access
- Configuration dataclass for database settings
- Utilities for future PostgreSQL migration

Current implementation uses aiosqlite (see connection.py).
This module prepares for future migration to PostgreSQL/SQLAlchemy.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Optional, Protocol, Sequence, runtime_checkable


@dataclass(frozen=True)
class DatabaseSettings:
    """Database connection settings."""

    url: str
    echo: bool = False
    pool_size: int = 5
    max_overflow: int = 10

    @classmethod
    def from_env(cls) -> "DatabaseSettings":
        """Create settings from environment variables."""
        return cls(
            url=os.environ.get("DATABASE_URL", "sqlite:///./data/tasks.db"),
            echo=os.environ.get("DATABASE_ECHO", "").lower() == "true",
        )

    @property
    def is_sqlite(self) -> bool:
        """Check if using SQLite."""
        return self.url.startswith("sqlite")

    @property
    def is_postgres(self) -> bool:
        """Check if using PostgreSQL."""
        return self.url.startswith("postgres")


@runtime_checkable
class DatabaseConnection(Protocol):
    """
    Protocol for database connections.

    This protocol defines the minimal interface that database connections
    must implement. It allows for type-safe database access while supporting
    different backends (SQLite, PostgreSQL).

    Current implementation: aiosqlite (connection.py)
    Future: SQLAlchemy async engine for PostgreSQL
    """

    async def execute(self, sql: str, parameters: Any = None) -> Any:
        """Execute a SQL statement."""
        ...

    async def fetch_one(self, sql: str, parameters: Any = None) -> Optional[dict]:
        """Execute query and fetch one row as dict."""
        ...

    async def fetch_all(self, sql: str, parameters: Any = None) -> Sequence[dict]:
        """Execute query and fetch all rows as dicts."""
        ...

    async def commit(self) -> None:
        """Commit current transaction."""
        ...

    async def rollback(self) -> None:
        """Rollback current transaction."""
        ...


@runtime_checkable
class DatabaseManager(Protocol):
    """
    Protocol for database manager.

    Manages database lifecycle and provides connection access.
    """

    async def init(self) -> None:
        """Initialize database connection and schema."""
        ...

    async def close(self) -> None:
        """Close database connection."""
        ...

    @property
    def connection(self) -> DatabaseConnection:
        """Get active connection."""
        ...


def parse_database_url(url: str) -> dict[str, Any]:
    """
    Parse database URL into components.

    Supports:
    - sqlite:///path/to/db.sqlite
    - postgresql://user:pass@host:port/dbname

    Returns:
        Dict with keys: dialect, driver, username, password, host, port, database
    """
    from urllib.parse import urlparse, parse_qs

    parsed = urlparse(url)

    # Handle SQLite special case
    if parsed.scheme == "sqlite":
        return {
            "dialect": "sqlite",
            "driver": None,
            "username": None,
            "password": None,
            "host": None,
            "port": None,
            "database": parsed.path.lstrip("/") or ":memory:",
        }

    # Handle PostgreSQL and others
    dialect_driver = parsed.scheme.split("+")
    dialect = dialect_driver[0]
    driver = dialect_driver[1] if len(dialect_driver) > 1 else None

    return {
        "dialect": dialect,
        "driver": driver,
        "username": parsed.username,
        "password": parsed.password,
        "host": parsed.hostname,
        "port": parsed.port,
        "database": parsed.path.lstrip("/"),
    }
