"""
Step 3: Crop and Stitch Images

Crops question images based on structure.json and stitches cross-page questions.
Generates final output images in all_questions/ directory.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any, Callable, List, Optional

from ..contracts import FatalError, StepContext, StepName, StepResult
from .base import BaseStepExecutor


class ComposeLongImageStep(BaseStepExecutor):
    """
    Crop and stitch question images.

    This step:
    1. Loads structure.json from Step 2
    2. Crops normal questions (stitching cross-page ones)
    3. Crops data analysis big questions (material + sub-questions)
    4. Saves all output to all_questions/

    Normal questions: q1.png, q2.png, ...
    Data analysis: data_analysis_1.png, data_analysis_2.png, ...
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
        return StepName.compose_long_image

    async def prepare(self, ctx: StepContext) -> None:
        """Validate structure.json exists."""
        from ..impl.structure_detection import has_structure_doc

        workdir = Path(ctx.workdir)

        if not has_structure_doc(workdir):
            raise FatalError(
                f"structure.json not found in {workdir}. Run analyze_data first."
            )

    async def execute(self, ctx: StepContext) -> StepResult:
        """Crop and stitch all question images."""
        start_time = time.time()

        workdir = Path(ctx.workdir)

        self._progress_callback(0.1)

        try:
            from ..impl.structure_detection import load_structure_doc
            from ..impl.crop_and_stitch import (
                process_structure_to_images,
                is_crop_complete,
            )

            # Load structure document
            structure_doc = await asyncio.to_thread(load_structure_doc, workdir)

            if structure_doc is None:
                raise FatalError("Failed to load structure.json")

            self._progress_callback(0.2)

            # Check if already completed (resume support)
            if is_crop_complete(workdir, structure_doc):
                # Manual mode: delete and rerun
                if ctx.metadata.get("mode") == "manual":
                    self._log("手动模式：删除已有输出，重新裁剪拼接")
                    output_dir = workdir / "all_questions"
                    if output_dir.exists():
                        import shutil
                        shutil.rmtree(output_dir)
                    output_dir.mkdir(parents=True, exist_ok=True)
                else:
                    # Auto mode: skip if exists
                    self._log("裁剪拼接已完成，跳过")
                    self._progress_callback(1.0)

                    # Collect existing output paths
                    output_dir = workdir / "all_questions"
                    normal_paths = [str(p) for p in output_dir.glob("q*.png")]
                    big_paths = [str(p) for p in output_dir.glob("data_analysis_*.png")]

                    elapsed = time.time() - start_time
                    return self._make_result(
                        success=True,
                        output_path=str(output_dir),
                        artifact_paths=normal_paths + big_paths,
                        elapsed_seconds=elapsed,
                        skipped=True,
                        normal_count=len(normal_paths),
                        big_count=len(big_paths),
                    )

            # Process structure to images
            self._log("开始裁剪拼接...")
            normal_paths, big_paths = await asyncio.to_thread(
                process_structure_to_images,
                workdir,
                structure_doc,
                self._log,
            )

            self._progress_callback(1.0)

            elapsed = time.time() - start_time

            all_paths = normal_paths + big_paths

            self._log(
                f"裁剪拼接完成: {len(normal_paths)} 道普通题, "
                f"{len(big_paths)} 个资料分析大题"
            )

            return self._make_result(
                success=True,
                output_path=str(workdir / "all_questions"),
                artifact_paths=all_paths,
                elapsed_seconds=elapsed,
                normal_count=len(normal_paths),
                big_count=len(big_paths),
            )

        except FatalError:
            raise
        except Exception as e:
            elapsed = time.time() - start_time
            error_msg = f"裁剪拼接出错: {e}"
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
        """Clean up all_questions directory on failure."""
        import shutil

        workdir = Path(ctx.workdir)
        output_dir = workdir / "all_questions"

        if output_dir.exists():
            shutil.rmtree(output_dir, ignore_errors=True)


def create_compose_long_image_step(
    log_callback: Optional[Callable[[str], None]] = None,
    progress_callback: Optional[Callable[[float], None]] = None,
) -> ComposeLongImageStep:
    """Factory function to create a ComposeLongImageStep."""
    return ComposeLongImageStep(
        log_callback=log_callback,
        progress_callback=progress_callback,
    )
