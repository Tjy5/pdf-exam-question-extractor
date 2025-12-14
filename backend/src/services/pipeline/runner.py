"""
Pipeline Runner - Orchestrates step execution with retry logic.

This module provides the PipelineRunner class that:
- Executes steps in sequence
- Handles retries with exponential backoff + jitter
- Supports task cancellation
- Emits progress events with structured logging
"""

from __future__ import annotations

import asyncio
import logging
import random
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from .contracts import (
    FatalError,
    RetryableError,
    StepContext,
    StepName,
    StepResult,
    StepStatus,
    TaskSnapshot,
    TaskStatus,
)
from .steps.base import StepExecutor


logger = logging.getLogger(__name__)

# Type alias for event callback
EventCallback = Callable[[str, Dict[str, Any]], None]


class PipelineRunner:
    """
    Orchestrates pipeline step execution.

    Features:
    - Sequential step execution
    - Retry with exponential backoff
    - Task cancellation
    - Progress event emission
    - Skip completed steps (resume support)

    Usage:
        runner = PipelineRunner(
            steps=[step0, step1, step2, step3, step4],
            max_retries=3,
            on_event=lambda event, data: print(f"{event}: {data}")
        )

        snapshot = await runner.run(initial_snapshot, context)
    """

    def __init__(
        self,
        steps: List[StepExecutor],
        max_retries: int = 3,
        retry_delay: float = 1.0,
        on_event: Optional[EventCallback] = None,
    ) -> None:
        """
        Initialize the runner.

        Args:
            steps: List of step executors in order
            max_retries: Maximum retry attempts per step
            retry_delay: Base delay between retries (exponential backoff)
            on_event: Callback for progress events
        """
        self._steps = steps
        self._max_retries = max_retries
        self._retry_delay = retry_delay
        self._on_event = on_event or (lambda e, d: None)

        # Cancellation tokens per task
        self._cancellation_tokens: Dict[str, asyncio.Event] = {}

    def _backoff_delay(self, attempt: int) -> float:
        """
        Calculate exponential backoff delay with jitter.

        Args:
            attempt: 1-based attempt number

        Returns:
            Delay in seconds with jitter to avoid thundering herd
        """
        base = self._retry_delay * (2 ** (attempt - 1))
        jitter = random.uniform(0, self._retry_delay * 0.5)
        return base + jitter

    async def _schedule_retry(
        self,
        *,
        task_id: str,
        step: StepExecutor,
        attempt: int,
        error: str,
    ) -> None:
        """Schedule retry with exponential backoff and emit events."""
        delay = self._backoff_delay(attempt)
        payload = {
            "task_id": task_id,
            "step": step.name.value,
            "attempt": attempt,
            "delay": round(delay, 2),
        }
        self._emit("step_retrying", payload)
        logger.warning(
            "Retrying step %s (attempt %d/%d) after %.2fs: %s",
            step.name.value,
            attempt,
            self._max_retries,
            delay,
            error,
            extra=payload,
        )
        await asyncio.sleep(delay)

    def _emit(self, event: str, data: Dict[str, Any]) -> None:
        """Emit an event to the callback."""
        try:
            self._on_event(event, data)
        except Exception:
            pass  # Don't let callback errors break the pipeline

    def _get_step_by_name(self, name: StepName) -> Optional[StepExecutor]:
        """Get step executor by name."""
        for step in self._steps:
            if step.name == name:
                return step
        return None

    async def run(
        self,
        snapshot: TaskSnapshot,
        ctx: StepContext,
        start_from_step: Optional[int] = None,
    ) -> TaskSnapshot:
        """
        Execute the pipeline for a task.

        Args:
            snapshot: Initial task snapshot
            ctx: Step context with paths and metadata
            start_from_step: Optional step index to start from (inclusive).
                Steps with a lower index are skipped.

        Returns:
            Final task snapshot after execution
        """
        task_id = snapshot.task_id

        # Validate start index
        if start_from_step is not None and (
            start_from_step < 0 or start_from_step >= len(self._steps)
        ):
            raise ValueError(
                f"start_from_step must be between 0 and {len(self._steps) - 1}"
            )

        # Create cancellation token
        self._cancellation_tokens[task_id] = asyncio.Event()

        try:
            # Update status to processing
            snapshot.status = TaskStatus.processing
            snapshot.updated_at = datetime.now()

            self._emit("pipeline_started", {"task_id": task_id})

            # Execute each step
            for idx, step in enumerate(self._steps):
                # Check for cancellation
                if self._cancellation_tokens[task_id].is_set():
                    self._emit("pipeline_cancelled", {"task_id": task_id})
                    break

                # Get step state
                step_state = snapshot.get_step_by_name(step.name)
                if step_state is None:
                    continue

                # Skip steps before start_from_step
                if start_from_step is not None and idx < start_from_step:
                    # Mark as skipped so pipeline can complete
                    if step_state.status != StepStatus.completed:
                        step_state.status = StepStatus.skipped
                        self._emit(
                            "step_skipped",
                            {
                                "task_id": task_id,
                                "step": step.name.value,
                                "reason": "before_start_from_step",
                            },
                        )
                    continue

                # Skip completed steps
                if step_state.status == StepStatus.completed:
                    self._emit(
                        "step_skipped",
                        {
                            "task_id": task_id,
                            "step": step.name.value,
                            "reason": "already_completed",
                        },
                    )
                    continue

                # Execute step with retry
                result = await self._execute_with_retry(
                    task_id, step, step_state.index, ctx
                )

                # Update step state
                step_state.status = (
                    StepStatus.completed if result.success else StepStatus.failed
                )
                step_state.ended_at = datetime.now()
                step_state.artifact_paths = result.artifact_paths
                step_state.error_message = result.error

                snapshot.updated_at = datetime.now()

                # Check for failure
                if not result.success:
                    # Steps 0, 1, 4 are critical
                    if step.name in [
                        StepName.pdf_to_images,
                        StepName.extract_questions,
                        StepName.collect_results,
                    ]:
                        snapshot.status = TaskStatus.failed
                        snapshot.error_message = result.error
                        snapshot.current_step = -1

                        self._emit(
                            "pipeline_failed",
                            {
                                "task_id": task_id,
                                "step": step.name.value,
                                "error": result.error,
                            },
                        )
                        return snapshot

            # Check if all steps completed or skipped
            all_completed = all(
                s.status in (StepStatus.completed, StepStatus.skipped)
                for s in snapshot.steps
            )

            if all_completed:
                snapshot.status = TaskStatus.completed
                snapshot.current_step = -1
                self._emit("pipeline_completed", {"task_id": task_id})
            else:
                # Some steps may have been skipped or are pending
                snapshot.status = TaskStatus.pending
                snapshot.current_step = -1

            return snapshot

        finally:
            # Cleanup cancellation token
            self._cancellation_tokens.pop(task_id, None)

    async def _execute_with_retry(
        self,
        task_id: str,
        step: StepExecutor,
        step_index: int,
        ctx: StepContext,
    ) -> StepResult:
        """
        Execute a step with retry logic.

        Uses exponential backoff with jitter for retryable errors.
        FatalError is never retried.
        """
        for attempt in range(1, self._max_retries + 1):
            log_ctx = {"task_id": task_id, "step": step.name.value, "attempt": attempt}

            try:
                self._emit(
                    "step_started",
                    {
                        "task_id": task_id,
                        "step": step.name.value,
                        "step_index": step_index,
                        "attempt": attempt,
                    },
                )

                await step.prepare(ctx)
                result = await step.execute(ctx)

                if result.success:
                    self._emit(
                        "step_completed",
                        {
                            "task_id": task_id,
                            "step": step.name.value,
                            "artifact_count": result.artifact_count,
                        },
                    )
                    logger.info("Step %s completed", step.name.value, extra=log_ctx)
                    return result

                # Step returned failure - check if retryable
                if not result.can_retry or attempt == self._max_retries:
                    self._emit(
                        "step_failed",
                        {
                            "task_id": task_id,
                            "step": step.name.value,
                            "error": result.error,
                            "can_retry": False,
                        },
                    )
                    logger.error(
                        "Step %s failed: %s",
                        step.name.value,
                        result.error,
                        extra={**log_ctx, "error": result.error},
                    )
                    return result

                # Schedule retry
                await self._schedule_retry(
                    task_id=task_id,
                    step=step,
                    attempt=attempt,
                    error=result.error or "unknown error",
                )

            except FatalError as e:
                # FatalError is never retried
                self._emit(
                    "step_failed",
                    {
                        "task_id": task_id,
                        "step": step.name.value,
                        "error": str(e),
                        "can_retry": False,
                    },
                )
                logger.exception("Fatal error in step %s", step.name.value, extra=log_ctx)
                return StepResult(
                    name=step.name,
                    success=False,
                    error=str(e),
                    can_retry=False,
                )

            except (RetryableError, Exception) as e:
                # RetryableError and unexpected exceptions are retried
                if attempt == self._max_retries:
                    self._emit(
                        "step_failed",
                        {
                            "task_id": task_id,
                            "step": step.name.value,
                            "error": str(e),
                            "can_retry": False,
                        },
                    )
                    logger.exception(
                        "Step %s failed after %d attempts",
                        step.name.value,
                        attempt,
                        extra={**log_ctx, "error": str(e)},
                    )
                    return StepResult(
                        name=step.name,
                        success=False,
                        error=str(e),
                        can_retry=False,
                    )

                await self._schedule_retry(
                    task_id=task_id,
                    step=step,
                    attempt=attempt,
                    error=str(e),
                )

        # Should not reach here
        return StepResult(
            name=step.name,
            success=False,
            error="Max retries exceeded",
            can_retry=False,
        )

    async def run_single_step(
        self,
        snapshot: TaskSnapshot,
        ctx: StepContext,
        step_index: int,
    ) -> TaskSnapshot:
        """
        Execute a single step (for manual mode).

        Args:
            snapshot: Current task snapshot
            ctx: Step context
            step_index: Index of step to execute

        Returns:
            Updated task snapshot
        """
        task_id = snapshot.task_id

        if step_index < 0 or step_index >= len(self._steps):
            raise ValueError(f"Invalid step index: {step_index}")

        step = self._steps[step_index]
        step_state = snapshot.get_step(step_index)

        if step_state is None:
            raise ValueError(f"Step state not found for index: {step_index}")

        # Update status
        snapshot.status = TaskStatus.processing
        snapshot.current_step = step_index
        step_state.status = StepStatus.running
        step_state.started_at = datetime.now()
        snapshot.updated_at = datetime.now()

        # Execute step
        result = await self._execute_with_retry(task_id, step, step_index, ctx)

        # Update step state
        step_state.status = (
            StepStatus.completed if result.success else StepStatus.failed
        )
        step_state.ended_at = datetime.now()
        step_state.artifact_paths = result.artifact_paths
        step_state.error_message = result.error

        # Update task status
        if not result.success and step.name in [
            StepName.pdf_to_images,
            StepName.extract_questions,
            StepName.collect_results,
        ]:
            snapshot.status = TaskStatus.failed
            snapshot.error_message = result.error
        else:
            # Check if all steps completed or skipped
            all_completed = all(
                s.status in (StepStatus.completed, StepStatus.skipped)
                for s in snapshot.steps
            )
            snapshot.status = (
                TaskStatus.completed if all_completed else TaskStatus.pending
            )

        snapshot.current_step = -1
        snapshot.updated_at = datetime.now()

        return snapshot

    def cancel(self, task_id: str) -> bool:
        """
        Cancel a running task.

        Args:
            task_id: Task to cancel

        Returns:
            True if cancellation was signaled, False if task not found
        """
        token = self._cancellation_tokens.get(task_id)
        if token:
            token.set()
            return True
        return False

    def is_running(self, task_id: str) -> bool:
        """Check if a task is currently running."""
        return task_id in self._cancellation_tokens
