"""
Task Executor Service

Bridges the Web Task model with the pipeline runner by:
- Creating step executors with Task-aware callbacks
- Feeding a PipelineRunner with TaskSnapshot/StepContext
- Running full or single-step pipelines in the background
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from ...common.paths import resolve_exam_dir_by_hash
from ...services.models.model_provider import PPStructureProvider
from ...services.pipeline import (
    PipelineRunner,
    StepContext,
    StepName,
    StepStatus as PipelineStepStatus,
    TaskSnapshot,
    TaskStatus as PipelineTaskStatus,
)
from ...services.pipeline.registry import StepRegistry

from ..config import config
from ..schemas import StepStatus as WebStepStatus
from .event_infra import emit_event
from .task_service import Task


class TaskExecutorService:
    """Executes pipeline steps for a Task with progress/state updates."""

    _STEP_INDEX = {
        StepName.pdf_to_images: 0,
        StepName.extract_questions: 1,
        StepName.analyze_data: 2,
        StepName.compose_long_image: 3,
        StepName.collect_results: 4,
    }

    def __init__(self, model_provider: Optional[PPStructureProvider] = None) -> None:
        self._model_provider = model_provider or PPStructureProvider.get_instance()
        self._background: Dict[str, asyncio.Task[Any]] = {}
        self._warmup_task: Optional[asyncio.Task[Any]] = None

    def start_full_pipeline(self, task: Task) -> asyncio.Task[Any]:
        """Kick off the full 5-step pipeline in the background."""
        return self._start(task, mode="auto")

    def start_single_step(self, task: Task, step_index: int) -> asyncio.Task[Any]:
        """Run only ONE step (manual mode)."""
        return self._start(task, mode="single", step_index=step_index)

    def start_from_step(self, task: Task, step_index: int) -> asyncio.Task[Any]:
        """Run from a specific step to the end (manual mode)."""
        return self._start(task, mode="from_step", step_index=step_index)

    def is_running(self, task_id: str) -> bool:
        """Check if a background job is active for the task."""
        handle = self._background.get(task_id)
        return bool(handle and not handle.done())

    def _start(
        self,
        task: Task,
        mode: str,
        step_index: Optional[int] = None,
    ) -> asyncio.Task[Any]:
        if task.id in self._background and not self._background[task.id].done():
            return self._background[task.id]

        if mode in ("single", "from_step") and step_index is None:
            raise ValueError("step_index is required for single/from_step mode")

        loop = asyncio.get_running_loop()
        if mode == "auto":
            coro = self._run_full(task)
        elif mode == "single":
            coro = self._run_single_step(task, step_index or 0)
        else:  # from_step
            coro = self._run_from_step(task, step_index or 0)

        handle = loop.create_task(coro, name=f"task-{task.id}-{mode}")
        self._background[task.id] = handle
        handle.add_done_callback(lambda t: self._background.pop(task.id, None))
        return handle

    async def _run_full(self, task: Task) -> None:
        try:
            await self._prepare_task_dirs(task)
            runner, snapshot, ctx = self._build_runner(task)
            final_snapshot = await runner.run(snapshot, ctx)
            self._sync_snapshot_to_task(final_snapshot, task)
            if final_snapshot.status == PipelineTaskStatus.completed:
                self._populate_results(task)
        except Exception as exc:
            self._on_pipeline_error(task, exc)

    async def _run_single_step(self, task: Task, step_index: int) -> None:
        """Run only ONE step (manual mode)."""
        try:
            await self._prepare_task_dirs(task)
            runner, snapshot, ctx = self._build_runner(task)
            result_snapshot = await runner.run_single_step(snapshot, ctx, step_index)
            self._sync_snapshot_to_task(result_snapshot, task)

            collect_idx = self._STEP_INDEX[StepName.collect_results]
            if (
                step_index == collect_idx
                and task.steps[collect_idx].status == WebStepStatus.COMPLETED
            ):
                self._populate_results(task)
        except Exception as exc:
            self._on_pipeline_error(task, exc)

    async def _run_from_step(self, task: Task, step_index: int) -> None:
        """Run from a specific step to the end (manual mode)."""
        try:
            await self._prepare_task_dirs(task)
            runner, snapshot, ctx = self._build_runner(task)
            final_snapshot = await runner.run(
                snapshot, ctx, start_from_step=step_index
            )
            self._sync_snapshot_to_task(final_snapshot, task)

            collect_idx = self._STEP_INDEX[StepName.collect_results]
            if task.steps[collect_idx].status == WebStepStatus.COMPLETED:
                self._populate_results(task)
        except Exception as exc:
            self._on_pipeline_error(task, exc)

    async def _prepare_task_dirs(self, task: Task) -> None:
        """Ensure exam dir exists and kick off async warmup if configured."""
        self._ensure_warmup_started()

        if not task.file_hash and task.pdf_path.is_file():
            try:
                task.file_hash = hashlib.sha256(task.pdf_path.read_bytes()).hexdigest()
            except Exception:
                pass

        if task.exam_dir and task.exam_dir.exists():
            return

        clean_name = Path(task.pdf_filename).stem
        exam_dir, exam_dir_name = resolve_exam_dir_by_hash(clean_name, task.file_hash)
        exam_dir.mkdir(parents=True, exist_ok=True)
        task.exam_dir = exam_dir
        task.add_log(f"工作目录: {exam_dir_name}", "info")

    def _build_runner(
        self,
        task: Task,
    ) -> tuple[PipelineRunner, TaskSnapshot, StepContext]:
        loop = asyncio.get_running_loop()
        steps = self._make_steps(task, loop)
        runner = PipelineRunner(
            steps=steps,
            max_retries=3,
            retry_delay=1.0,
            on_event=lambda event, data: self._handle_event(task, event, data),
        )

        snapshot = self._build_snapshot(task)
        ctx = StepContext(
            task_id=task.id,
            pdf_path=str(task.pdf_path),
            workdir=str(task.exam_dir),
            file_hash=task.file_hash,
            expected_pages=task.expected_pages,
            metadata={"mode": task.mode},
        )
        return runner, snapshot, ctx

    def _make_steps(
        self, task: Task, loop: asyncio.AbstractEventLoop
    ) -> List[Any]:
        """
        Build step executors using StepRegistry.

        Each step factory has different kwargs requirements. We use a parameter
        mapping dictionary to centralize the configuration and make it easier
        to add new steps.
        """
        log_cb = self._log_adapter(task, loop)
        names = StepRegistry.get_ordered_names()
        factories = StepRegistry.get_ordered_factories()

        # Helper to build common progress callback parameters
        def _progress_kwargs(step_index: int) -> Dict[str, Any]:
            return {
                "log_callback": log_cb,
                "progress_callback": self._progress_adapter(task, loop, step_index),
            }

        steps: List[Any] = []
        for idx, (name, factory) in enumerate(zip(names, factories)):
            # Parameter mapping: step name -> kwargs for that step's factory
            # This centralizes step configuration and makes extension easier
            param_map: Dict[str, Dict[str, Any]] = {
                StepName.pdf_to_images.value: _progress_kwargs(idx),
                StepName.extract_questions.value: {
                    "model_provider": self._model_provider,
                    "skip_existing": True,
                    "parallel": config.parallel_extraction,
                    "max_workers": config.max_workers,
                    "log_callback": log_cb,
                    "progress_callback": self._extract_progress_adapter(task, loop, idx),
                },
                StepName.analyze_data.value: {
                    "model_provider": self._model_provider,
                    **_progress_kwargs(idx),
                },
                StepName.compose_long_image.value: _progress_kwargs(idx),
                StepName.collect_results.value: _progress_kwargs(idx),
            }

            params = param_map.get(name)
            if params is None:
                raise ValueError(f"Unsupported step in registry: {name}")

            step = factory(**params)
            steps.append(step)

        return steps

    def _progress_adapter(
        self,
        task: Task,
        loop: asyncio.AbstractEventLoop,
        step_index: int,
    ):
        # Coalesce high-frequency callbacks from worker threads to avoid
        # flooding loop.call_soon_threadsafe (which can stall the event loop).
        lock = threading.Lock()
        pending: Optional[float] = None
        scheduled = False

        def _flush() -> None:
            nonlocal pending, scheduled
            with lock:
                value = pending
                pending = None
                scheduled = False
            if value is None:
                return
            task.update_step_progress(step_index, max(0.0, min(1.0, float(value))))

        def _cb(progress: float) -> None:
            nonlocal pending, scheduled
            v = max(0.0, min(1.0, float(progress)))
            with lock:
                pending = v
                if scheduled:
                    return
                scheduled = True
            loop.call_soon_threadsafe(_flush)

        return _cb

    def _extract_progress_adapter(
        self,
        task: Task,
        loop: asyncio.AbstractEventLoop,
        step_index: int,
    ):
        lock = threading.Lock()
        pending: Optional[float] = None
        scheduled = False

        def _flush() -> None:
            nonlocal pending, scheduled
            with lock:
                value = pending
                pending = None
                scheduled = False
            if value is None:
                return
            task.update_step_progress(step_index, max(0.0, min(1.0, float(value))))

        def _cb(done: int, total: int, status: str = "", page_name: str = "") -> None:
            nonlocal pending, scheduled
            value = (float(done) / float(total)) if total else 0.0
            v = max(0.0, min(1.0, float(value)))
            with lock:
                pending = v
                if not scheduled:
                    scheduled = True
                    loop.call_soon_threadsafe(_flush)

            # Per-page status logs can be extremely noisy; default to sampled + live-only.
            # - Always log errors
            # - Optionally log every N pages (EXAMPAPER_EXTRACT_LOG_EVERY_N)
            # - Always log final completion
            try:
                log_every_n = int(os.getenv("EXAMPAPER_EXTRACT_LOG_EVERY_N", "0") or "0")
            except (ValueError, TypeError):
                log_every_n = 0

            want_log = False
            if status:
                if status.lower() in {"error", "failed", "exception"}:
                    want_log = True
                elif total and done >= total:
                    want_log = True
                elif log_every_n > 0 and (done % max(1, log_every_n) == 0):
                    want_log = True

            if want_log and status:
                message = status if not page_name else f"{status}: {page_name}"
                # Live-only to avoid SQLite commit storms
                loop.call_soon_threadsafe(task.add_log, message, "info", False)

        return _cb

    def _log_adapter(
        self,
        task: Task,
        loop: asyncio.AbstractEventLoop,
        log_type: str = "info",
    ):
        # Default: keep important logs durable, downgrade noisy OCR progress logs to live-only.
        ocr_live_only = (os.getenv("EXAMPAPER_OCR_LOG_LIVE_ONLY", "1") or "").strip() == "1"

        def _is_noisy(message: str) -> bool:
            if not message:
                return False
            m = message.strip()
            # Patterns from OCR/parallel_extraction that can fire per page or more.
            return (
                m.startswith("[并发]")
                or m.startswith("[OCR]")
                or m.startswith("  [OCR]")
                or "GPU推理中" in m
                or m.startswith("  [处理]")
                or m.startswith("  [跳过]")
                or m.startswith("  [空页]")
            )

        def _cb(message: str) -> None:
            durable = True
            if log_type in {"error", "warning"}:
                durable = True
            elif ocr_live_only and _is_noisy(message):
                durable = False
            loop.call_soon_threadsafe(task.add_log, message, log_type, durable)

        return _cb

    def _handle_event(self, task: Task, event: str, data: Dict[str, Any]) -> None:
        idx = self._step_index_from_name(data.get("step") if isinstance(data, dict) else None)

        if event == "pipeline_started":
            task.status = "processing"
            task.error_message = None
            task.add_log("任务开始执行", "info")
        elif event == "step_started":
            if idx is not None:
                task.mark_step_running(idx)
            task.status = "processing"
        elif event == "step_retrying":
            if idx is not None:
                task.add_log(f"步骤重试，第 {data.get('attempt', 1)} 次", "info")
        elif event == "step_skipped":
            reason = data.get("reason", "") if isinstance(data, dict) else ""
            if idx is not None:
                step = task.get_step(idx)
                # Don't downgrade COMPLETED to SKIPPED
                if step and step.status != WebStepStatus.COMPLETED:
                    step.status = WebStepStatus.SKIPPED
                    step.progress = None
                    step.started_at = step.started_at or datetime.now()
                    step.ended_at = datetime.now()
                    task.updated_at = datetime.now()
            if reason:
                task.add_log(f"跳过步骤: {reason}", "info")
        elif event == "step_completed":
            if idx is not None:
                task.mark_step_completed(idx)
                task.current_step = -1
        elif event == "step_failed":
            error = data.get("error") if isinstance(data, dict) else None
            if idx is not None:
                task.mark_step_failed(idx, error or "未知错误")
                task.current_step = -1
            task.status = "failed"
            task.error_message = error or "任务失败"
        elif event == "pipeline_failed":
            error = data.get("error") if isinstance(data, dict) else None
            task.status = "failed"
            task.current_step = -1
            task.error_message = error or "任务失败"
            task.add_log(task.error_message, "error")
            emit_event(task_id=task.id, event_type="done", payload={"status": "error"})
        elif event == "pipeline_completed":
            task.status = "completed"
            task.current_step = -1
            task.add_log("流水线执行完成", "success")
            emit_event(task_id=task.id, event_type="done", payload={"status": "completed"})
        elif event == "pipeline_cancelled":
            task.status = "pending"
            task.current_step = -1
            task.add_log("任务已取消", "info")

    def _build_snapshot(self, task: Task) -> TaskSnapshot:
        snapshot = TaskSnapshot.create_new(
            task_id=task.id,
            pdf_name=task.pdf_filename,
            mode=task.mode,
            file_hash=task.file_hash,
            workdir=str(task.exam_dir) if task.exam_dir else None,
            expected_pages=task.expected_pages,
        )

        try:
            snapshot.status = PipelineTaskStatus(task.status)
        except ValueError:
            snapshot.status = PipelineTaskStatus.pending
        snapshot.current_step = task.current_step

        for step_state in snapshot.steps:
            web_step = task.get_step(step_state.index)
            if not web_step:
                continue
            step_state.status = self._map_web_step_status(web_step.status)
            step_state.started_at = web_step.started_at
            step_state.ended_at = web_step.ended_at
            step_state.artifact_paths = web_step.artifact_paths
            step_state.error_message = web_step.error_message

        return snapshot

    def _sync_snapshot_to_task(self, snapshot: TaskSnapshot, task: Task) -> None:
        for step_state in snapshot.steps:
            web_step = task.get_step(step_state.index)
            if not web_step:
                continue

            web_step.status = self._map_pipeline_step_status(step_state.status)
            if web_step.status == WebStepStatus.COMPLETED:
                web_step.progress = 1.0
            elif web_step.status in (WebStepStatus.PENDING, WebStepStatus.FAILED):
                web_step.progress = None

            web_step.started_at = step_state.started_at
            web_step.ended_at = step_state.ended_at
            web_step.artifact_paths = step_state.artifact_paths
            web_step.error_message = step_state.error_message

        task.status = snapshot.status.value
        task.current_step = snapshot.current_step
        task.error_message = snapshot.error_message
        if snapshot.workdir:
            task.exam_dir = Path(snapshot.workdir)

    def _map_web_step_status(
        self, status: WebStepStatus
    ) -> PipelineStepStatus:
        mapping = {
            WebStepStatus.PENDING: PipelineStepStatus.pending,
            WebStepStatus.RUNNING: PipelineStepStatus.running,
            WebStepStatus.COMPLETED: PipelineStepStatus.completed,
            WebStepStatus.FAILED: PipelineStepStatus.failed,
            WebStepStatus.SKIPPED: PipelineStepStatus.skipped,
        }
        return mapping.get(status, PipelineStepStatus.pending)

    def _map_pipeline_step_status(
        self, status: PipelineStepStatus
    ) -> WebStepStatus:
        mapping = {
            PipelineStepStatus.pending: WebStepStatus.PENDING,
            PipelineStepStatus.running: WebStepStatus.RUNNING,
            PipelineStepStatus.completed: WebStepStatus.COMPLETED,
            PipelineStepStatus.failed: WebStepStatus.FAILED,
            PipelineStepStatus.skipped: WebStepStatus.SKIPPED,
        }
        return mapping.get(status, WebStepStatus.PENDING)

    def _step_index_from_name(self, step_name: Optional[str]) -> Optional[int]:
        if not step_name:
            return None
        try:
            return self._STEP_INDEX[StepName(step_name)]
        except Exception:
            return None

    def _populate_results(self, task: Task) -> None:
        if not task.exam_dir:
            return
        all_dir = task.exam_dir / "all_questions"
        if not all_dir.is_dir():
            return
        task.result_images = [
            {"filename": p.name, "name": p.stem, "path": str(p)}
            for p in sorted(all_dir.glob("*.png"))
        ]

    def _ensure_warmup_started(self) -> None:
        if (
            self._warmup_task
            or not config.ppstructure_warmup
            or not config.ppstructure_warmup_async
        ):
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        self._warmup_task = loop.create_task(
            self._model_provider.warmup(), name="ppstructure-warmup"
        )

    def _on_pipeline_error(self, task: Task, exc: Exception) -> None:
        task.status = "failed"
        task.current_step = -1
        task.error_message = str(exc)
        task.add_log(f"任务执行异常: {exc}", "error")
        emit_event(task_id=task.id, event_type="done", payload={"status": "error"})


# Global executor instance
task_executor = TaskExecutorService()
