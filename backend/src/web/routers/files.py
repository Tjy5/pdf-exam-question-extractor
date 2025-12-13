"""
Files Router - API endpoints for file downloads and image serving
"""
import shutil
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from ..services.task_service import task_manager

router = APIRouter(prefix="/api", tags=["files"])


@router.get("/image/{task_id}/{filename}")
async def serve_image(task_id: str, filename: str):
    """Serve an individual result image"""
    task = task_manager.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    if not task.exam_dir:
        raise HTTPException(status_code=400, detail="Task not yet processed")

    image_path = task.exam_dir / "all_questions" / filename

    if not image_path.exists():
        raise HTTPException(status_code=404, detail="Image not found")

    return FileResponse(image_path, media_type="image/png")


@router.get("/download/{task_id}")
async def download_results(task_id: str):
    """Download all results as a ZIP file"""
    task = task_manager.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    if not task.exam_dir:
        raise HTTPException(status_code=400, detail="Task not yet processed")

    all_questions_dir = task.exam_dir / "all_questions"
    if not all_questions_dir.exists():
        raise HTTPException(status_code=404, detail="No results to download")

    zip_path = task.exam_dir / f"{task_id}_results.zip"
    shutil.make_archive(str(zip_path.with_suffix("")), "zip", all_questions_dir)

    return FileResponse(
        zip_path,
        media_type="application/zip",
        filename=f"exam_questions_{task_id}.zip",
    )
