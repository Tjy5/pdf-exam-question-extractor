"""
Model provider for PP-StructureV3 lifecycle management.

This module provides a singleton ModelProvider that manages the PP-StructureV3
OCR model lifecycle, including:
- Lazy initialization
- Thread-safe inference
- GPU memory management
- Warmup and shutdown
"""

from __future__ import annotations

import asyncio
import threading
from contextlib import contextmanager
from datetime import datetime
from typing import Any, ContextManager, Optional


class PPStructureProvider:
    """
    Singleton provider for PP-StructureV3 model.

    Manages the model lifecycle with thread-safe access for inference.
    Uses a combination of asyncio locks (for async code) and threading
    locks (for sync inference calls).

    Usage:
        provider = PPStructureProvider.get_instance()
        await provider.warmup()

        with provider.lease() as pipeline:
            result = pipeline.predict(image)

        await provider.shutdown()
    """

    _instance: Optional["PPStructureProvider"] = None
    _instance_lock = threading.Lock()

    def __init__(self) -> None:
        """Initialize the provider. Use get_instance() instead."""
        self._pipeline: Any = None
        self._warmup_lock = asyncio.Lock()
        self._predict_lock = threading.RLock()

        # Status tracking
        self._ready = False
        self._warmup_error: Optional[str] = None
        self._warmup_started_at: Optional[datetime] = None
        self._warmup_ended_at: Optional[datetime] = None

    @classmethod
    def get_instance(cls) -> "PPStructureProvider":
        """Get the singleton instance."""
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """Reset the singleton instance (for testing)."""
        with cls._instance_lock:
            if cls._instance is not None:
                cls._instance._pipeline = None
                cls._instance._ready = False
            cls._instance = None

    @property
    def is_ready(self) -> bool:
        """Check if the model is ready for inference."""
        return self._ready and self._pipeline is not None

    @property
    def warmup_error(self) -> Optional[str]:
        """Get the warmup error message, if any."""
        return self._warmup_error

    def get_status(self) -> dict:
        """Get detailed status information."""
        return {
            "ready": self._ready,
            "warmup_error": self._warmup_error,
            "warmup_started_at": (
                self._warmup_started_at.isoformat()
                if self._warmup_started_at
                else None
            ),
            "warmup_ended_at": (
                self._warmup_ended_at.isoformat() if self._warmup_ended_at else None
            ),
            "pipeline_loaded": self._pipeline is not None,
        }

    async def warmup(self, force: bool = False) -> bool:
        """
        Load and warm up the PP-StructureV3 model.

        Args:
            force: If True, reload even if already loaded

        Returns:
            True if warmup succeeded, False otherwise
        """
        async with self._warmup_lock:
            if self._ready and not force:
                return True

            self._warmup_started_at = datetime.now()
            self._warmup_error = None

            try:
                # Import and initialize PP-StructureV3
                from ...common.ocr_models import get_ppstructure, warmup_ppstructure

                # Load the pipeline
                self._pipeline = await asyncio.to_thread(get_ppstructure)

                # Run warmup inference
                await asyncio.to_thread(warmup_ppstructure)

                self._ready = True
                self._warmup_ended_at = datetime.now()
                return True

            except Exception as e:
                self._ready = False
                self._warmup_error = f"{type(e).__name__}: {e}"
                self._warmup_ended_at = datetime.now()
                return False

    async def ensure_ready(self) -> None:
        """
        Ensure the model is ready, warming up if necessary.

        Raises:
            RuntimeError: If warmup fails
        """
        if self._ready:
            return

        success = await self.warmup()
        if not success:
            raise RuntimeError(f"Model warmup failed: {self._warmup_error}")

    @contextmanager
    def lease(self) -> ContextManager[Any]:
        """
        Context manager for thread-safe model access.

        Acquires the predict lock and yields the pipeline.
        Use this for all inference calls.

        Usage:
            with provider.lease() as pipeline:
                result = pipeline.predict(image)

        Yields:
            The PP-StructureV3 pipeline instance
        """
        if not self._ready or self._pipeline is None:
            raise RuntimeError("Model not ready. Call warmup() first.")

        with self._predict_lock:
            yield self._pipeline

    def get_pipeline_unsafe(self) -> Any:
        """
        Get the pipeline without locking.

        WARNING: Only use this if you're managing locking yourself.
        Prefer lease() for thread-safe access.

        Returns:
            The PP-StructureV3 pipeline instance, or None if not loaded
        """
        return self._pipeline

    async def shutdown(self) -> None:
        """
        Shutdown the model and release resources.

        Should be called on application shutdown.
        """
        async with self._warmup_lock:
            self._pipeline = None
            self._ready = False


class ThreadSafePipeline:
    """
    Thread-safe wrapper for PP-StructureV3 pipeline.

    Wraps a pipeline instance and serializes predict() calls
    using a threading lock.

    Usage:
        raw_pipeline = get_ppstructure()
        safe_pipeline = ThreadSafePipeline(raw_pipeline, lock)
        result = safe_pipeline.predict(image)
    """

    def __init__(self, pipeline: Any, lock: threading.RLock) -> None:
        """
        Initialize the wrapper.

        Args:
            pipeline: The underlying PP-StructureV3 pipeline
            lock: Threading lock for serialization
        """
        self._pipeline = pipeline
        self._lock = lock

    def predict(self, *args: Any, **kwargs: Any) -> Any:
        """
        Thread-safe predict call.

        Acquires the lock before calling the underlying pipeline.
        """
        with self._lock:
            return self._pipeline.predict(*args, **kwargs)

    def __getattr__(self, name: str) -> Any:
        """Delegate other attributes to the underlying pipeline."""
        return getattr(self._pipeline, name)
