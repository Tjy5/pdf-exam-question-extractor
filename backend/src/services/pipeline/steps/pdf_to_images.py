"""
Step 0: PDF to Images

Converts PDF pages to high-resolution PNG images using PyMuPDF (fitz).
Supports parallel rendering via ProcessPoolExecutor for multi-core speedup.
"""

from __future__ import annotations

import asyncio
import os
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Callable, List, Optional, Tuple

from ..contracts import FatalError, RetryableError, StepContext, StepName, StepResult
from .base import BaseStepExecutor


def _render_page(args: Tuple[str, int, str, int]) -> Tuple[int, str]:
    """
    Worker function for parallel PDF page rendering.
    Must be module-level for ProcessPoolExecutor pickling.
    """
    import fitz
    pdf_path, page_num, out_path, dpi = args
    doc = fitz.open(pdf_path)
    try:
        page = doc[page_num]
        pix = page.get_pixmap(dpi=dpi)
        pix.save(out_path)
        return page_num, out_path
    finally:
        doc.close()


class PdfToImagesStep(BaseStepExecutor):
    """
    Convert PDF pages to PNG images.

    This step:
    1. Opens the PDF file
    2. Renders each page at 300 DPI
    3. Saves as page_1.png, page_2.png, etc.

    Supports skip_existing to reuse previously converted pages.
    """

    def __init__(
        self,
        dpi: int = 300,
        skip_existing: bool = True,
        log_callback: Optional[Callable[[str], None]] = None,
        progress_callback: Optional[Callable[[float], None]] = None,
    ) -> None:
        """
        Initialize the step.

        Args:
            dpi: Resolution for rendering (default 300)
            skip_existing: Skip pages that already exist
            log_callback: Optional callback for logging
            progress_callback: Optional callback for progress (0.0-1.0)
        """
        self._dpi = dpi
        self._skip_existing = skip_existing
        self._log = log_callback or (lambda m: None)
        self._progress_callback = progress_callback or (lambda p: None)

    @property
    def name(self) -> StepName:
        return StepName.pdf_to_images

    async def prepare(self, ctx: StepContext) -> None:
        """Validate PDF exists and is readable."""
        pdf_path = Path(ctx.pdf_path)

        if not pdf_path.exists():
            raise FatalError(f"PDF file not found: {pdf_path}")

        if not pdf_path.suffix.lower() == ".pdf":
            raise FatalError(f"Not a PDF file: {pdf_path}")

        # Try to open the PDF to validate it
        try:
            import fitz

            doc = fitz.open(pdf_path)
            doc.close()
        except Exception as e:
            raise FatalError(f"Cannot open PDF: {e}")

    async def execute(self, ctx: StepContext) -> StepResult:
        """Convert PDF to images with parallel rendering."""
        start_time = time.time()

        pdf_path = Path(ctx.pdf_path)
        workdir = Path(ctx.workdir)
        workdir.mkdir(parents=True, exist_ok=True)

        try:
            import fitz

            doc = fitz.open(pdf_path)
            total_pages = len(doc)
            doc.close()

            self._log(f"开始转换 PDF，共 {total_pages} 页")

            artifact_paths: List[str] = [""] * total_pages
            skipped_count = 0
            tasks_to_run: List[Tuple[str, int, str, int]] = []

            for page_num in range(total_pages):
                img_name = f"page_{page_num + 1}.png"
                img_path = workdir / img_name

                if self._skip_existing and img_path.exists():
                    artifact_paths[page_num] = str(img_path)
                    skipped_count += 1
                else:
                    tasks_to_run.append((str(pdf_path), page_num, str(img_path), self._dpi))

            converted_count = 0
            if tasks_to_run:
                max_workers = min(len(tasks_to_run), os.cpu_count() or 4)
                self._log(f"  并行渲染 {len(tasks_to_run)} 页 (workers={max_workers})")

                loop = asyncio.get_running_loop()
                with ProcessPoolExecutor(max_workers=max_workers) as executor:
                    futures = {executor.submit(_render_page, t): t[1] for t in tasks_to_run}
                    for future in as_completed(futures):
                        page_num = futures[future]
                        try:
                            _, out_path = future.result()
                            artifact_paths[page_num] = out_path
                            converted_count += 1
                            done = skipped_count + converted_count
                            self._progress_callback(done / total_pages)
                        except Exception as e:
                            raise RuntimeError(f"Page {page_num + 1} render failed: {e}")
            else:
                self._progress_callback(1.0)

            elapsed = time.time() - start_time

            if skipped_count > 0:
                self._log(f"PDF 转图片完成: 转换 {converted_count} 页, 跳过 {skipped_count} 页")
            else:
                self._log(f"PDF 转图片完成: 共 {total_pages} 页")

            return self._make_result(
                success=True,
                output_path=str(workdir),
                artifact_paths=artifact_paths,
                elapsed_seconds=elapsed,
                total_pages=total_pages,
                converted_pages=converted_count,
                skipped_pages=skipped_count,
            )

        except Exception as e:
            elapsed = time.time() - start_time
            error_msg = f"PDF 转图片失败: {e}"
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

        We don't delete page images on failure because:
        1. They may be reused on retry
        2. Partial conversion is still useful
        """
        pass


def create_pdf_to_images_step(
    dpi: int = 300,
    skip_existing: bool = True,
    log_callback: Optional[Callable[[str], None]] = None,
    progress_callback: Optional[Callable[[float], None]] = None,
) -> PdfToImagesStep:
    """Factory function to create a PdfToImagesStep."""
    return PdfToImagesStep(
        dpi=dpi,
        skip_existing=skip_existing,
        log_callback=log_callback,
        progress_callback=progress_callback,
    )
