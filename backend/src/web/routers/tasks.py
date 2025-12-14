"""
Tasks Router - API endpoints for task management
"""
import asyncio
import hashlib
import json

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse

from ..limiter import limiter
from ..schemas import ProcessRequest, StepStatus
from ..services.event_bus import event_bus
from ..services.task_executor import task_executor
from ..services.task_service import task_manager

router = APIRouter(prefix="/api", tags=["tasks"])


def _format_sse(event: str, data: object) -> str:
    """Encode data as SSE-formatted string."""
    if isinstance(data, str):
        return f"event: {event}\ndata: {data}\n\n"
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.get("/stream/{task_id}")
async def stream_task(task_id: str, last_log_index: int = 0):
    """
    Server-Sent Events stream for a task.

    Sends:
    - step: whenever any step status/progress changes
    - log: for each new log entry
    - done: once when task finishes (completed/error)

    Query params:
    - last_log_index: skip logs before this index on reconnect (default 0)
    """
    task = task_manager.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    async def event_generator():
        queue = await event_bus.subscribe(task_id)
        last_sent_log = max(0, last_log_index)
        try:
            # Send current snapshot
            yield _format_sse("step", {"steps": task.serialize_steps()})

            # Send any backlog logs (from last_sent_log)
            for log in task.logs[last_sent_log:]:
                yield _format_sse("log", log.dict())
                last_sent_log += 1

            # If already finished, send done and exit
            if task.status in ("completed", "failed"):
                yield _format_sse("done", "completed" if task.status == "completed" else "error")
                return

            while True:
                event = await queue.get()
                etype = event.get("type")
                if etype == "log":
                    yield _format_sse("log", event.get("data", {}))
                elif etype == "step":
                    yield _format_sse("step", event.get("data", {}))
                elif etype == "done":
                    yield _format_sse("done", event.get("data"))
                    break
        except asyncio.CancelledError:
            pass
        finally:
            await event_bus.unsubscribe(task_id, queue)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.post("/upload")
@limiter.limit("10/minute")
async def upload_pdf(request: Request, file: UploadFile = File(...), mode: str = Form("auto")):
    """Upload a PDF file and create a new task"""
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are accepted")

    if mode not in ["auto", "manual"]:
        raise HTTPException(status_code=400, detail="Mode must be 'auto' or 'manual'")

    task = task_manager.create_task(file.filename, mode)

    content = await file.read()
    task.file_hash = hashlib.sha256(content).hexdigest()
    task.pdf_path.write_bytes(content)

    task.add_log(
        f"文件上传成功: {file.filename} (模式: {mode}, hash: {task.file_hash[:8]})",
        "success",
    )

    return {
        "task_id": task.id,
        "filename": file.filename,
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

    return {"status": task.status, "images": task.result_images}
