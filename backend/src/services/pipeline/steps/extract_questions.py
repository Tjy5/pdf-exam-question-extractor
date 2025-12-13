"""
Step 1: Extract Questions

Uses PP-StructureV3 to detect and extract individual questions from page images.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any, Callable, List, Optional

from ..contracts import FatalError, RetryableError, StepContext, StepName, StepResult
from .base import BaseStepExecutor


class ExtractQuestionsStep(BaseStepExecutor):
    """
    Extract questions from page images using PP-StructureV3.

    This step:
    1. Loads page images from workdir
    2. Runs OCR layout analysis on each page
    3. Detects question boundaries
    4. Crops and saves individual question images
    5. Generates meta.json for each page

    Supports parallel processing and skip_existing.
    """

    def __init__(
        self,
        model_provider: Any,
        skip_existing: bool = True,
        parallel: bool = False,
        max_workers: int = 4,
        log_callback: Optional[Callable[[str], None]] = None,
        progress_callback: Optional[Callable[[int, int, str, str], None]] = None,
    ) -> None:
        """
        Initialize the step.

        Args:
            model_provider: PPStructureProvider instance
            skip_existing: Skip pages with existing meta.json
            parallel: Enable parallel processing
            max_workers: Number of parallel workers
            log_callback: Optional callback for logging
            progress_callback: Optional callback for progress (done, total, status, page_name)
        """
        self._model_provider = model_provider
        self._skip_existing = skip_existing
        self._parallel = parallel
        self._max_workers = max_workers
        self._log = log_callback or (lambda m: None)
        self._progress_callback = progress_callback

    @property
    def name(self) -> StepName:
        return StepName.extract_questions

    async def prepare(self, ctx: StepContext) -> None:
        """Ensure model is ready and page images exist."""
        workdir = Path(ctx.workdir)

        # Check page images exist
        page_images = list(workdir.glob("page_*.png"))
        if not page_images:
            raise FatalError(f"No page images found in {workdir}")

        # Ensure model is ready
        await self._model_provider.ensure_ready()

    async def execute(self, ctx: StepContext) -> StepResult:
        """Extract questions from all pages."""
        start_time = time.time()

        workdir = Path(ctx.workdir)

        try:
            # Import the extraction function from the new implementation
            from ..impl.extract_questions import run_extract_questions

            # Get thread-safe pipeline
            with self._model_provider.lease() as pipeline:
                # Run extraction in thread pool
                success = await asyncio.to_thread(
                    run_extract_questions,
                    img_dir=workdir,
                    pipeline=pipeline,
                    skip_existing=self._skip_existing,
                    pages=[],  # Process all pages
                    log=self._log,
                    parallel=self._parallel,
                    max_workers=self._max_workers,
                    progress_callback=self._progress_callback,
                )

            elapsed = time.time() - start_time

            if success:
                # Collect artifact paths
                artifact_paths: List[str] = []
                for questions_dir in workdir.glob("questions_page_*"):
                    artifact_paths.extend([str(p) for p in questions_dir.glob("*.png")])

                self._log(f"题目提取完成: 共 {len(artifact_paths)} 个题目图片")

                return self._make_result(
                    success=True,
                    output_path=str(workdir),
                    artifact_paths=artifact_paths,
                    elapsed_seconds=elapsed,
                    question_count=len(artifact_paths),
                )
            else:
                return self._make_result(
                    success=False,
                    error="题目提取失败",
                    can_retry=True,
                    elapsed_seconds=elapsed,
                )

        except Exception as e:
            elapsed = time.time() - start_time
            error_msg = f"题目提取出错: {e}"
            self._log(error_msg)

            return self._make_result(
                success=False,
                error=error_msg,
                can_retry=True,
                elapsed_seconds=elapsed,
            )

    async def rollback(self, ctx: StepContext) -> None:
        """
        Rollback is a no-op for this step.

        Partial extraction results are kept for retry.
        """
        pass


def create_extract_questions_step(
    model_provider: Any,
    skip_existing: bool = True,
    parallel: bool = False,
    max_workers: int = 4,
    log_callback: Optional[Callable[[str], None]] = None,
    progress_callback: Optional[Callable[[int, int, str, str], None]] = None,
) -> ExtractQuestionsStep:
    """Factory function to create an ExtractQuestionsStep."""
    return ExtractQuestionsStep(
        model_provider=model_provider,
        skip_existing=skip_existing,
        parallel=parallel,
        max_workers=max_workers,
        log_callback=log_callback,
        progress_callback=progress_callback,
    )
