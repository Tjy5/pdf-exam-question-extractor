"""
Base step executor protocol and utilities.

This module defines the StepExecutor protocol that all pipeline steps must implement,
along with helper utilities for step implementation.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Callable, Optional, Protocol, runtime_checkable

from ..contracts import StepContext, StepName, StepResult


@runtime_checkable
class StepExecutor(Protocol):
    """
    Protocol for pipeline step executors.

    Each step in the processing pipeline must implement this protocol.
    Steps should be idempotent where possible - running the same step
    twice with the same input should produce the same output.

    Example:
        class MyStep:
            @property
            def name(self) -> StepName:
                return StepName.my_step

            async def execute(self, ctx: StepContext) -> StepResult:
                # Do work...
                return StepResult(name=self.name, success=True)
    """

    @property
    def name(self) -> StepName:
        """Return the name of this step."""
        ...

    async def prepare(self, ctx: StepContext) -> None:
        """
        Pre-flight checks and warmup.

        This method is called before execute() and should:
        - Validate input paths exist
        - Check required resources are available
        - Perform any warmup (e.g., model loading)

        Should NOT have side effects on the filesystem.
        Raise RetryableError or FatalError on failure.
        """
        ...

    async def execute(self, ctx: StepContext) -> StepResult:
        """
        Execute the step.

        This is the main entry point for step execution.
        Should return a StepResult indicating success/failure.

        Args:
            ctx: Step context with input paths and metadata

        Returns:
            StepResult with success status and output paths
        """
        ...

    async def rollback(self, ctx: StepContext) -> None:
        """
        Rollback partial side effects on failure.

        Called when execute() fails partway through.
        Should clean up any partial outputs to allow retry.
        """
        ...


class BaseStepExecutor(ABC):
    """
    Abstract base class for step executors.

    Provides default implementations for prepare() and rollback(),
    leaving only execute() to be implemented by subclasses.
    """

    @property
    @abstractmethod
    def name(self) -> StepName:
        """Return the name of this step."""
        pass

    @property
    def title(self) -> str:
        """Human-readable title for this step."""
        titles = {
            StepName.pdf_to_images: "PDF 转图片",
            StepName.extract_questions: "题目提取",
            StepName.analyze_data: "资料分析重组",
            StepName.compose_long_image: "长图拼接",
            StepName.collect_results: "结果汇总",
        }
        return titles.get(self.name, str(self.name))

    async def prepare(self, ctx: StepContext) -> None:
        """
        Default prepare implementation - no-op.

        Override in subclasses to add validation or warmup.
        """
        pass

    @abstractmethod
    async def execute(self, ctx: StepContext) -> StepResult:
        """Execute the step. Must be implemented by subclasses."""
        pass

    async def rollback(self, ctx: StepContext) -> None:
        """
        Default rollback implementation - no-op.

        Override in subclasses to clean up partial outputs.
        """
        pass

    def _make_result(
        self,
        success: bool,
        output_path: Optional[str] = None,
        artifact_paths: Optional[list] = None,
        error: Optional[str] = None,
        can_retry: bool = True,
        **metrics: float,
    ) -> StepResult:
        """Helper to create a StepResult."""
        return StepResult(
            name=self.name,
            success=success,
            output_path=output_path,
            artifact_paths=artifact_paths or [],
            artifact_count=len(artifact_paths) if artifact_paths else 0,
            metrics=metrics,
            error=error,
            can_retry=can_retry,
        )


# Type alias for step factory function
StepFactory = Callable[[], StepExecutor]
