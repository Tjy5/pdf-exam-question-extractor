"""
Step 2: Analyze Data (Structure Detection)

Analyzes OCR cache to build document structure, detecting data analysis sections
and constructing the question graph.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any, Callable, List, Optional

from ..contracts import FatalError, StepContext, StepName, StepResult
from .base import BaseStepExecutor


class AnalyzeDataStep(BaseStepExecutor):
    """
    Analyze document structure from OCR cache.

    This step:
    1. Loads OCR cache from Step 1
    2. Detects data analysis section boundaries
    3. Builds question graph (normal vs data_analysis questions)
    4. Outputs structure.json

    This step does NOT call OCR - it uses cached results from Step 1.
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
        return StepName.analyze_data

    async def prepare(self, ctx: StepContext) -> None:
        """Ensure OCR cache exists."""
        from ..impl.ocr_cache import is_ocr_complete

        workdir = Path(ctx.workdir)

        if not is_ocr_complete(workdir):
            raise FatalError(
                f"OCR cache incomplete in {workdir}. Run extract_questions first."
            )

    async def execute(self, ctx: StepContext) -> StepResult:
        """Build document structure from OCR cache."""
        start_time = time.time()

        workdir = Path(ctx.workdir)

        self._progress_callback(0.1)

        try:
            from ..impl.ocr_cache import load_all_ocr_caches
            from ..impl.structure_detection import (
                build_structure_doc,
                save_structure_doc,
                has_structure_doc,
            )

            # Check if already completed (resume support)
            if has_structure_doc(workdir):
                # Manual mode: delete and rerun
                if ctx.metadata.get("mode") == "manual":
                    self._log("手动模式：删除已有结构文档，重新分析")
                    structure_file = workdir / "structure.json"
                    if structure_file.exists():
                        structure_file.unlink()
                else:
                    # Auto mode: skip if exists
                    self._log("结构文档已存在，跳过")
                    self._progress_callback(1.0)

                    elapsed = time.time() - start_time
                    return self._make_result(
                        success=True,
                        output_path=str(workdir),
                        artifact_paths=[str(workdir / "structure.json")],
                        elapsed_seconds=elapsed,
                        skipped=True,
                    )

            # Load all OCR caches
            self._log("加载 OCR 缓存...")
            ocr_caches = await asyncio.to_thread(load_all_ocr_caches, workdir)

            if not ocr_caches:
                raise FatalError("No OCR cache files found")

            self._progress_callback(0.3)

            # Build structure document
            self._log("构建文档结构...")
            structure_doc = await asyncio.to_thread(
                build_structure_doc,
                ocr_caches,
                self._log,
            )

            self._progress_callback(0.8)

            # Save structure document
            structure_path = await asyncio.to_thread(
                save_structure_doc, workdir, structure_doc
            )

            self._progress_callback(1.0)

            elapsed = time.time() - start_time

            # Summary
            normal_count = len(structure_doc.get_normal_questions())
            big_count = len(structure_doc.big_questions)

            self._log(
                f"结构检测完成: {normal_count} 道普通题, {big_count} 个资料分析大题"
            )

            return self._make_result(
                success=True,
                output_path=str(workdir),
                artifact_paths=[str(structure_path)],
                elapsed_seconds=elapsed,
                normal_question_count=normal_count,
                big_question_count=big_count,
            )

        except FatalError:
            raise
        except Exception as e:
            elapsed = time.time() - start_time
            error_msg = f"结构检测出错: {e}"
            self._log(error_msg)

            return self._make_result(
                success=False,
                output_path=str(workdir),
                artifact_paths=[],
                error=error_msg,
                can_retry=True,
                elapsed_seconds=elapsed,
            )

    async def rollback(self, ctx: StepContext) -> None:
        """Remove structure.json on failure."""
        workdir = Path(ctx.workdir)
        structure_path = workdir / "structure.json"

        if structure_path.exists():
            structure_path.unlink()


def create_analyze_data_step(
    log_callback: Optional[Callable[[str], None]] = None,
    progress_callback: Optional[Callable[[float], None]] = None,
    model_provider: Any = None,  # Kept for API compatibility, but not used
) -> AnalyzeDataStep:
    """Factory function to create an AnalyzeDataStep."""
    return AnalyzeDataStep(
        log_callback=log_callback,
        progress_callback=progress_callback,
    )
