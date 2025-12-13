"""
Tasks module - Task state management.

This module will contain TaskService for managing task lifecycle.
"""

# Re-export from db module for convenience
from ...db import TaskRepository

__all__ = ["TaskRepository"]
