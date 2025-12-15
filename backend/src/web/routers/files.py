"""
Files Router - API endpoints for file downloads and image serving
"""
import shutil

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from ..services.task_service import task_manager

router = APIRouter(prefix="/api", tags=["files"])


@router.get("/image/{task_id}/{filename}")
async def serve_image(task_id: str, filename: str):
    """Serve an individual result image with path traversal protection"""
    task = task_manager.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    if not task.exam_dir:
        raise HTTPException(status_code=400, detail="Task not yet processed")

    # Security: Reject filenames containing path separators to prevent:
    # - Path traversal attacks (e.g., "../../sensitive_file")
    # - Absolute path injection (e.g., "C:\Windows\win.ini")
    if "/" in filename or "\\" in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")

    # Security: Only allow PNG image files
    if not filename.lower().endswith(".png"):
        raise HTTPException(status_code=400, detail="Only PNG files are allowed")

    # Security: Normalize paths and enforce boundary check
    # This ensures the resolved path stays within the allowed directory
    base_dir = (task.exam_dir / "all_questions").resolve()

    # Verify base directory exists
    if not base_dir.is_dir():
        raise HTTPException(status_code=404, detail="Results directory not found")

    image_path = (base_dir / filename).resolve()

    # Security: Verify the resolved path is within base_dir
    try:
        image_path.relative_to(base_dir)
    except ValueError:
        # Path escaped the allowed directory - deny access
        raise HTTPException(status_code=403, detail="Access denied")

    # Verify file exists and is a regular file after boundary check
    if not image_path.exists() or not image_path.is_file():
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
