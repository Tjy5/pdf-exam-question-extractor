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
import functools
import os
import threading
from concurrent.futures import ThreadPoolExecutor
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

    # Shared GPU semaphore (process-level, limits concurrent GPU inference)
    _gpu_semaphore: Optional[threading.Semaphore] = None
    _gpu_semaphore_lock = threading.Lock()

    # Lock for lazy initialization of GPU executor (instance-level)
    _gpu_executor_lock = threading.Lock()

    def __init__(self) -> None:
        """Initialize the provider. Use get_instance() instead."""
        self._pipeline: Any = None
        self._pipeline_wrapped: Any = None
        self._warmup_lock = asyncio.Lock()
        self._predict_lock = threading.RLock()

        # Optional: bind all predict() calls to a single OS thread to avoid
        # Paddle/CUDA thread-affinity hangs in async + high-worker web environments.
        self._gpu_executor: Optional[ThreadPoolExecutor] = None
        self._gpu_thread_ident: Optional[int] = None

        # Enabled by default for web stability (can be disabled via env).
        self._thread_bound_predict = (
            (os.getenv("EXAMPAPER_PPSTRUCTURE_THREAD_BOUND_PREDICT", "1") or "").strip()
            == "1"
        )

        # Status tracking
        self._ready = False
        self._warmup_error: Optional[str] = None
        self._warmup_started_at: Optional[datetime] = None
        self._warmup_ended_at: Optional[datetime] = None

        # Initialize shared GPU semaphore if not already done
        self._init_gpu_semaphore()

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
                executor = getattr(cls._instance, "_gpu_executor", None)
                if executor is not None:
                    try:
                        executor.shutdown(wait=False, cancel_futures=True)
                    except Exception:
                        pass
                cls._instance._pipeline = None
                cls._instance._pipeline_wrapped = None
                cls._instance._gpu_executor = None
                cls._instance._gpu_thread_ident = None
                cls._instance._ready = False
            cls._instance = None

    def _thread_bound_enabled(self) -> bool:
        """
        Thread-bound predict is only safe/useful when GPU concurrency <= 1.
        If EXAMPAPER_GPU_CONCURRENCY > 1, force-disable to avoid collapsing
        intended GPU parallelism back to 1 and increasing semaphore hold times.
        """
        if not self._thread_bound_predict:
            return False
        try:
            gpu_concurrency = int(os.getenv("EXAMPAPER_GPU_CONCURRENCY", "1") or "1")
        except (TypeError, ValueError):
            gpu_concurrency = 1
        return gpu_concurrency <= 1

    def _ensure_gpu_executor(self) -> ThreadPoolExecutor:
        """
        Ensure GPU executor is created (thread-safe lazy initialization).

        Uses a lock to prevent race conditions when multiple threads
        concurrently call this method for the first time.
        """
        if self._gpu_executor is None:
            with self._gpu_executor_lock:
                # Double-check after acquiring lock
                if self._gpu_executor is None:
                    self._gpu_executor = ThreadPoolExecutor(
                        max_workers=1, thread_name_prefix="ppstructure-gpu"
                    )
        return self._gpu_executor

    def _get_pipeline_for_inference(self) -> Any:
        """
        Get the pipeline for inference, with optional thread-binding wrapper.

        Returns the raw pipeline or a thread-bound wrapper depending on
        configuration. Uses lazy initialization with locking for thread safety.

        Note: This is called from event loop thread during normal operation,
        but uses locking to be safe against rare multi-threaded access patterns.
        """
        if not self._ready or self._pipeline is None:
            raise RuntimeError("Model not ready. Call warmup() first.")

        if not self._thread_bound_enabled():
            return self._pipeline

        # Lazy create wrapped pipeline with thread safety
        if self._pipeline_wrapped is None:
            with self._gpu_executor_lock:
                # Double-check after acquiring lock
                if self._pipeline_wrapped is None:
                    executor = self._ensure_gpu_executor()
                    if self._gpu_thread_ident is None:
                        try:
                            self._gpu_thread_ident = executor.submit(
                                threading.get_ident
                            ).result(timeout=5)
                        except Exception:
                            self._gpu_thread_ident = None
                    self._pipeline_wrapped = _ThreadBoundPipeline(
                        pipeline=self._pipeline,
                        executor=executor,
                        executor_thread_ident=self._gpu_thread_ident,
                    )
        return self._pipeline_wrapped

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

                # IMPORTANT:
                # Keep get_ppstructure() + warmup_ppstructure() on the SAME OS thread.
                # Two separate asyncio.to_thread() calls are not guaranteed to reuse the same thread.
                def _load_and_warmup() -> tuple[Any, int]:
                    pipeline = get_ppstructure()
                    warmup_ppstructure()
                    return pipeline, threading.get_ident()

                if self._thread_bound_enabled():
                    loop = asyncio.get_running_loop()
                    executor = self._ensure_gpu_executor()
                    pipeline, tid = await loop.run_in_executor(executor, _load_and_warmup)
                    self._pipeline = pipeline
                    self._gpu_thread_ident = tid
                else:
                    pipeline, _tid = await asyncio.to_thread(_load_and_warmup)
                    self._pipeline = pipeline
                    self._gpu_thread_ident = None

                # Reset wrapped pipeline (lazy recreate with current settings)
                self._pipeline_wrapped = None

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
            yield self._get_pipeline_for_inference()

    def get_pipeline_unsafe(self) -> Any:
        """
        Get the raw pipeline without locking or thread-binding wrapper.

        WARNING: Only use this if you're managing locking yourself.
        Prefer lease() for thread-safe access or get_pipeline() for production use.

        IMPORTANT: This returns the raw pipeline, bypassing thread-binding.
        Do NOT use this for inference in production - use get_pipeline() instead,
        which respects thread-binding configuration.

        Returns:
            The raw PP-StructureV3 pipeline instance, or None if not loaded
        """
        return self._pipeline

    def get_pipeline(self) -> Any:
        """
        Get the pipeline for use with external GPU semaphore.

        This returns the pipeline without holding the predict lock,
        allowing multiple tasks to process concurrently with GPU-level
        synchronization handled by the shared semaphore.

        Returns:
            The PP-StructureV3 pipeline instance

        Raises:
            RuntimeError: If model is not ready
        """
        return self._get_pipeline_for_inference()

    @classmethod
    def _init_gpu_semaphore(cls) -> None:
        """Initialize the shared GPU semaphore from environment variable."""
        if cls._gpu_semaphore is not None:
            return

        with cls._gpu_semaphore_lock:
            if cls._gpu_semaphore is not None:
                return

            # Parse GPU_CONCURRENCY from environment (default: 1)
            try:
                gpu_concurrency = int(os.getenv("EXAMPAPER_GPU_CONCURRENCY", "1"))
                gpu_concurrency = max(1, min(gpu_concurrency, 8))  # Clamp to [1, 8]
            except (ValueError, TypeError):
                gpu_concurrency = 1

            cls._gpu_semaphore = threading.Semaphore(gpu_concurrency)

    @classmethod
    def get_gpu_semaphore(cls) -> threading.Semaphore:
        """
        Get the shared GPU semaphore.

        This semaphore should be passed to ParallelPageProcessor to
        ensure proper GPU concurrency control across multiple tasks.

        Returns:
            The shared GPU semaphore instance
        """
        if cls._gpu_semaphore is None:
            cls._init_gpu_semaphore()
        return cls._gpu_semaphore

    async def shutdown(self) -> None:
        """
        Shutdown the model and release resources.

        Should be called on application shutdown.
        """
        async with self._warmup_lock:
            self._pipeline = None
            self._pipeline_wrapped = None
            self._ready = False
            self._gpu_thread_ident = None

            executor = self._gpu_executor
            self._gpu_executor = None
            if executor is not None:
                try:
                    executor.shutdown(wait=False, cancel_futures=True)
                except Exception:
                    pass


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


class _ThreadBoundPipeline:
    """
    Execute pipeline.predict() on a dedicated OS thread (ThreadPoolExecutor max_workers=1).

    Notes:
    - Worker threads will block on .result(), but GPU inference is already serialized by
      the existing semaphore when EXAMPAPER_GPU_CONCURRENCY<=1.
    - If called from the executor thread itself, run predict() inline to avoid deadlock.
    """

    def __init__(
        self,
        pipeline: Any,
        executor: ThreadPoolExecutor,
        executor_thread_ident: Optional[int],
    ) -> None:
        self._pipeline = pipeline
        self._executor = executor
        self._executor_thread_ident = executor_thread_ident

    def predict(self, *args: Any, **kwargs: Any) -> Any:
        if (
            self._executor_thread_ident is not None
            and threading.get_ident() == self._executor_thread_ident
        ):
            return self._pipeline.predict(*args, **kwargs)
        fn = functools.partial(self._pipeline.predict, *args, **kwargs)
        return self._executor.submit(fn).result()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._pipeline, name)
