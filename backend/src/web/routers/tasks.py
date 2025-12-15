"""
Tasks Router - API endpoints for task management
"""
import asyncio
import hashlib
import json
import logging
import shutil
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse

from ...common.paths import resolve_exam_dir_by_hash
from ...db.connection import get_db_manager
from ...db.crud import TaskRepository
from ..limiter import limiter
from ..schemas import ProcessRequest, StepStatus
from ..services.event_bus import event_bus
from ..services.event_infra import get_event_store
from ..services.task_executor import task_executor
from ..services.task_service import task_manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["tasks"])


def _format_sse(event: str, data: object, event_id: int | None = None) -> str:
    """Encode data as SSE-formatted string with optional event ID."""
    lines = []
    if event_id is not None:
        lines.append(f"id: {event_id}")
    lines.append(f"event: {event}")
    if isinstance(data, str):
        lines.append(f"data: {data}")
    else:
        lines.append(f"data: {json.dumps(data, ensure_ascii=False)}")
    lines.append("")
    lines.append("")
    return "\n".join(lines)


@router.get("/stream/{task_id}")
async def stream_task(
    task_id: str,
    request: Request,
    last_event_id: int | None = None,
):
    """
    Server-Sent Events stream for a task with replay support.

    Sends:
    - step: whenever any step status/progress changes
    - log: for each new log entry
    - done: once when task finishes (completed/error)

    Query params:
    - last_event_id: replay events after this ID (for SSE reconnection)

    Headers:
    - Last-Event-ID: alternative to last_event_id query param (standard SSE)
    """
    task = task_manager.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    # Support Last-Event-ID header (standard SSE reconnection)
    header_last_id = request.headers.get("Last-Event-ID")
    if header_last_id and last_event_id is None:
        try:
            last_event_id = int(header_last_id)
        except ValueError:
            pass

    async def event_generator():
        store = get_event_store()
        queue = await event_bus.subscribe(task_id)
        after_id = max(0, int(last_event_id or 0))
        cursor = after_id  # Track highest event ID seen

        def _extract_live_event_id(evt: dict) -> int | None:
            """Extract event ID from live event (may be at top level or in data)."""
            top = evt.get("_event_id")
            if isinstance(top, int):
                return top
            data = evt.get("data")
            if isinstance(data, dict) and isinstance(data.get("_event_id"), int):
                return int(data["_event_id"])
            return None

        def _normalize_done_data(data: object) -> str:
            """Normalize done event data to plain string for frontend compatibility."""
            if isinstance(data, str):
                return data
            if isinstance(data, dict):
                v = data.get("status") or data.get("value") or ""
                return str(v)
            return str(data)

        try:
            # 0) Always send a bootstrap snapshot (NO id!) for immediate UI state
            yield _format_sse("step", {"steps": task.serialize_steps()})

            # 1) Replay durable events from SQLite (if reconnecting)
            limit = 500
            while True:
                batch = await store.list_since(task_id=task_id, after_id=cursor, limit=limit)
                if not batch:
                    break
                for ev in batch:
                    data = ev.payload
                    if ev.event_type == "done":
                        data = _normalize_done_data(data)
                    yield _format_sse(ev.event_type, data, event_id=ev.id)
                    cursor = ev.id
                if len(batch) < limit:
                    break

            # 2) Drain any live events that arrived during replay (dedupe by id)
            while True:
                try:
                    live = queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
                etype = live.get("type")
                data = live.get("data")
                eid = _extract_live_event_id(live)
                # Skip if already sent during replay
                if eid is not None and eid <= cursor:
                    continue
                if etype == "done":
                    yield _format_sse("done", _normalize_done_data(data), event_id=eid)
                    return
                if eid is not None:
                    cursor = eid
                    yield _format_sse(str(etype), data, event_id=eid)
                else:
                    yield _format_sse(str(etype), data)

            # 3) Live streaming loop with heartbeat
            while True:
                if await request.is_disconnected():
                    break
                try:
                    live = await asyncio.wait_for(queue.get(), timeout=15.0)
                except asyncio.TimeoutError:
                    # Send heartbeat to keep connection alive
                    yield ": keep-alive\n\n"
                    continue

                etype = live.get("type")
                data = live.get("data")
                eid = _extract_live_event_id(live)

                # Skip duplicates
                if eid is not None and eid <= cursor:
                    continue

                if etype == "done":
                    yield _format_sse("done", _normalize_done_data(data), event_id=eid)
                    break

                if eid is not None:
                    cursor = eid
                    yield _format_sse(str(etype), data, event_id=eid)
                else:
                    yield _format_sse(str(etype), data)

        except asyncio.CancelledError:
            pass
        finally:
            await event_bus.unsubscribe(task_id, queue)

    headers = {
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",  # Disable Nginx buffering
    }
    return StreamingResponse(event_generator(), media_type="text/event-stream", headers=headers)


@router.post("/upload")
@limiter.limit("10/minute")
async def upload_pdf(request: Request, file: UploadFile = File(...), mode: str = Form("auto")):
    """Upload a PDF file and create a new task"""
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are accepted")

    if mode not in ["auto", "manual"]:
        raise HTTPException(status_code=400, detail="Mode must be 'auto' or 'manual'")

    # Step 1: Create in-memory task
    task = task_manager.create_task(file.filename, mode)

    # Step 2: Read file content and compute hash
    content = await file.read()
    file_hash = hashlib.sha256(content).hexdigest()

    # Step 3: Calculate exam directory using server-normalized filename
    # Use task.pdf_filename (already normalized in Task.__init__) for consistency
    clean_name = Path(task.pdf_filename).stem
    exam_dir, exam_dir_name = resolve_exam_dir_by_hash(clean_name, file_hash)

    # Step 4: Write PDF to filesystem
    try:
        task.pdf_path.write_bytes(content)
        exam_dir.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        # Cleanup: Remove in-memory task and task workdir on filesystem failure
        task_manager.tasks.pop(task.id, None)
        task_manager.task_locks.pop(task.id, None)
        if task.task_workdir.exists():
            shutil.rmtree(task.task_workdir, ignore_errors=True)
        # Log detailed error for debugging, but return generic message to client
        logger.error(f"Failed to save PDF for task {task.id}: {exc}", exc_info=True)
        raise HTTPException(
            status_code=500, detail="Failed to save uploaded file"
        ) from exc

    # Step 5: Update task attributes
    task.file_hash = file_hash
    task.exam_dir = exam_dir

    # Step 6: Create database record
    # CRITICAL: This MUST happen before any emit_event call (e.g., task.add_log)
    # because events have a foreign key constraint to tasks table
    try:
        db = get_db_manager()
        repo = TaskRepository(db)
        await repo.create_task(
            task_id=task.id,
            mode=mode,
            pdf_name=task.pdf_filename,  # Use normalized filename for consistency
            file_hash=file_hash,
            exam_dir_name=exam_dir_name,
            expected_pages=None,  # Will be determined during PDF conversion
        )
    except Exception as exc:
        # Cleanup: Remove filesystem and in-memory task on database failure
        task_manager.tasks.pop(task.id, None)
        task_manager.task_locks.pop(task.id, None)
        if task.task_workdir.exists():
            shutil.rmtree(task.task_workdir, ignore_errors=True)
        # Log detailed error for debugging, but return generic message to client
        logger.error(f"Failed to create task {task.id} in database: {exc}", exc_info=True)
        raise HTTPException(
            status_code=500, detail="Failed to create task record"
        ) from exc

    # Step 7: Now safe to emit events (database record exists)
    task.add_log(
        f"文件上传成功: {task.pdf_filename} (模式: {mode}, hash: {file_hash[:8]}, 目录: {exam_dir_name})",
        "success",
    )

    return {
        "task_id": task.id,
        "filename": task.pdf_filename,  # Return normalized filename for consistency
        "mode": mode,
        "steps": [
            {
                "index": step.index,
                "name": step.name,
                "title": step.title,
                "status": step.status.value,
            }
            for step in task.steps
        ],
    }


@router.post("/process")
@limiter.limit("20/minute")
async def start_processing(request: Request, payload: ProcessRequest):
    """Start processing a task"""
    task = task_manager.get_task(payload.task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    if task.status == "processing" or task_executor.is_running(payload.task_id):
        return {"message": "Task is already processing", "mode": task.mode}

    if task.mode == "auto":
        task_executor.start_full_pipeline(task)
        return {"message": "Full pipeline started", "mode": "auto"}
    else:
        return {
            "message": "Task is in manual mode. Use /api/tasks/{task_id}/steps/{step_index}/start",
            "mode": "manual",
        }


@router.get("/status/{task_id}")
async def get_status(task_id: str, since: int = 0):
    """Get current status and logs for a task"""
    task = task_manager.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    new_logs = []
    for idx, log in enumerate(task.logs[since:], start=since):
        log_id = getattr(log, "id", None) or f"{task_id}-{idx}"
        entry = log.dict()
        entry["id"] = log_id
        new_logs.append(entry)

    return {
        "task_id": task_id,
        "status": task.status,
        "mode": task.mode,
        "current_step": task.current_step,
        "steps": [
            {
                "index": step.index,
                "name": step.name,
                "title": step.title,
                "status": step.status.value,
                "progress": step.progress,
                "started_at": step.started_at.isoformat() if step.started_at else None,
                "ended_at": step.ended_at.isoformat() if step.ended_at else None,
                "artifact_count": len(step.artifact_paths),
                "error": step.error_message,
            }
            for step in task.steps
        ],
        "logs": new_logs,
        "total_logs": len(task.logs),
        "error": task.error_message,
    }


@router.post("/tasks/{task_id}/steps/{step_index}/start")
async def start_step(task_id: str, step_index: int, run_to_end: bool = False):
    """Start execution of a specific step (manual mode)

    Args:
        run_to_end: If True, run from this step to the end. If False, run only this step.
    """
    task = task_manager.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    if step_index < 0 or step_index >= len(task.steps):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid step index: {step_index}. Must be between 0 and {len(task.steps) - 1}",
        )

    if task.mode != "manual":
        raise HTTPException(
            status_code=409,
            detail=f"Task is in {task.mode} mode. Manual step execution is only available for manual mode tasks.",
        )

    if task_executor.is_running(task_id):
        raise HTTPException(status_code=409, detail="Task is already processing")

    if task.steps[step_index].status == StepStatus.FAILED:
        task.reset_step(step_index)

    can_run, error_msg = task.can_run_step(step_index)
    if not can_run:
        raise HTTPException(status_code=409, detail=error_msg)

    if run_to_end:
        task_executor.start_from_step(task, step_index)
        message = f"从步骤 {task.steps[step_index].title} 开始执行到最后"
    else:
        task_executor.start_single_step(task, step_index)
        message = f"步骤 {task.steps[step_index].title} 已开始执行"

    step = task.steps[step_index]
    return {
        "task_id": task_id,
        "step": {
            "index": step.index,
            "name": step.name,
            "title": step.title,
            "status": step.status.value,
        },
        "message": message,
    }


@router.get("/tasks/{task_id}/steps/{step_index}/results")
async def get_step_results(task_id: str, step_index: int):
    """Get results from a specific step"""
    task = task_manager.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    if step_index < 0 or step_index >= len(task.steps):
        raise HTTPException(status_code=400, detail=f"Invalid step index: {step_index}")

    step = task.steps[step_index]

    if step.status == StepStatus.PENDING:
        raise HTTPException(status_code=409, detail="步骤尚未执行")

    return {
        "task_id": task_id,
        "step": {
            "index": step.index,
            "name": step.name,
            "title": step.title,
            "status": step.status.value,
            "started_at": step.started_at.isoformat() if step.started_at else None,
            "ended_at": step.ended_at.isoformat() if step.ended_at else None,
            "artifact_count": len(step.artifact_paths),
            "artifacts": step.artifact_paths[:10],
            "error": step.error_message,
        },
    }


@router.post("/tasks/{task_id}/restart/{from_step}")
async def restart_from_step(task_id: str, from_step: int):
    """Restart a task from a given step"""
    task = task_manager.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    if from_step < 0 or from_step >= len(task.steps):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid step index: {from_step}. Must be between 0 and {len(task.steps) - 1}",
        )

    if task.status == "processing":
        raise HTTPException(status_code=409, detail="Task is processing, cannot restart")

    lock = task_manager.get_task_lock(task_id)
    async with lock:
        for idx in range(from_step, len(task.steps)):
            step = task.steps[idx]
            step.status = StepStatus.PENDING
            step.progress = None
            step.error_message = None
            step.artifact_paths = []
            step.started_at = None
            step.ended_at = None

        task.status = "pending"
        task.current_step = -1

    return {
        "task_id": task_id,
        "from_step": from_step,
        "steps": [
            {
                "index": step.index,
                "name": step.name,
                "title": step.title,
                "status": step.status.value,
            }
            for step in task.steps
        ],
        "message": f"已重置步骤 {from_step + 1} 及后续步骤",
    }


@router.get("/results/{task_id}")
async def get_results(task_id: str):
    """Get the list of generated images for a completed task"""
    task = task_manager.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    return {"task_id": task_id, "status": task.status, "images": task.result_images}
