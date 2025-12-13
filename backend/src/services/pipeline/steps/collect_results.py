"""
Step 4: Collect Results

Final step - validates output and generates summary metadata.
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Callable, List, Optional

from ..contracts import FatalError, StepContext, StepName, StepResult
from .base import BaseStepExecutor


class CollectResultsStep(BaseStepExecutor):
    """
    Collect and validate final results.

    This step:
    1. Validates all_questions/ directory exists and has content
    2. Counts normal questions and data analysis big questions
    3. Generates final summary metadata
    4. This is the final step - produces the user-facing output

    Note: Since Step 3 now directly generates output to all_questions/,
    this step is mainly for validation and metadata generation.
    """

    def __init__(
        self,
        log_callback: Optional[Callable[[str], None]] = None,
        progress_callback: Optional[Callable[[float], None]] = None,
    ) -> None:
        """
        Initialize the step.

        Args:
            log_callback: Optional callback for logging
            progress_callback: Optional callback for progress (0.0-1.0)
        """
        self._log = log_callback or (lambda m: None)
        self._progress_callback = progress_callback or (lambda p: None)

    @property
    def name(self) -> StepName:
        return StepName.collect_results

    async def prepare(self, ctx: StepContext) -> None:
        """Validate workdir and all_questions exist."""
        workdir = Path(ctx.workdir)

        if not workdir.exists():
            raise FatalError(f"Workdir not found: {workdir}")

        all_dir = workdir / "all_questions"
        if not all_dir.exists():
            raise FatalError(
                f"all_questions directory not found. Run compose_long_image first."
            )

    async def execute(self, ctx: StepContext) -> StepResult:
        """Collect and validate results."""
        start_time = time.time()

        workdir = Path(ctx.workdir)
        all_dir = workdir / "all_questions"

        self._progress_callback(0.1)

        try:
            # Collect all output files
            normal_files = sorted(all_dir.glob("q*.png"))
            big_files = sorted(all_dir.glob("data_analysis_*.png"))

            self._progress_callback(0.5)

            # Validate
            if not normal_files and not big_files:
                self._log("警告: all_questions 目录为空")
                return self._make_result(
                    success=True,
                    output_path=str(all_dir),
                    artifact_paths=[],
                    elapsed_seconds=time.time() - start_time,
                    question_count=0,
                )

            # Generate summary
            artifact_paths = [str(f) for f in normal_files] + [str(f) for f in big_files]

            # Extract question numbers for summary
            normal_qnos = []
            for f in normal_files:
                try:
                    qno = int(f.stem[1:])  # Remove 'q' prefix
                    normal_qnos.append(qno)
                except ValueError:
                    pass

            big_ids = [f.stem for f in big_files]

            # Generate summary metadata
            summary = {
                "total_questions": len(artifact_paths),
                "normal_questions": len(normal_files),
                "big_questions": len(big_files),
                "normal_qno_range": [min(normal_qnos), max(normal_qnos)] if normal_qnos else None,
                "big_question_ids": big_ids,
            }

            summary_path = all_dir / "summary.json"
            await asyncio.to_thread(
                self._write_summary, summary_path, summary
            )

            self._progress_callback(1.0)

            elapsed = time.time() - start_time

            self._log(
                f"结果汇总完成: {len(normal_files)} 道普通题, "
                f"{len(big_files)} 个资料分析大题"
            )

            return self._make_result(
                success=True,
                output_path=str(all_dir),
                artifact_paths=artifact_paths,
                elapsed_seconds=elapsed,
                question_count=len(artifact_paths),
                normal_count=len(normal_files),
                big_count=len(big_files),
            )

        except Exception as e:
            elapsed = time.time() - start_time
            error_msg = f"结果汇总出错: {e}"
            self._log(error_msg)

            return self._make_result(
                success=False,
                error=error_msg,
                can_retry=True,
                elapsed_seconds=elapsed,
            )

    def _write_summary(self, path: Path, summary: dict) -> None:
        """Write summary JSON file."""
        with path.open("w", encoding="utf-8") as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)

    async def rollback(self, ctx: StepContext) -> None:
        """Rollback is a no-op for this step."""
        pass


def create_collect_results_step(
    log_callback: Optional[Callable[[str], None]] = None,
    progress_callback: Optional[Callable[[float], None]] = None,
) -> CollectResultsStep:
    """Factory function to create a CollectResultsStep."""
    return CollectResultsStep(
        log_callback=log_callback,
        progress_callback=progress_callback,
    )
