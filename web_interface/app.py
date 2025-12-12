"""
FastAPI Web Interface for Exam Paper Processing System
基于现有CLI脚本构建的Web服务，提供友好的前端界面

Architecture:
- FastAPI for async HTTP API
- In-memory task tracking (可扩展为SQLite持久化)
- Background asyncio subprocess execution with real-time log streaming
- File management per task with unique workdirs
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
import shutil
import sys
import uuid
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Dict, List, Literal, Optional

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# Ensure project root is on sys.path even when started from web_interface/
# (start_web.bat does `cd web_interface`).
PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# 共享路径/状态管理工具
from src.common.paths import resolve_exam_dir_by_hash
from src.common.io import load_job_meta, save_job_meta

# Task Status Types
TaskStatus = Literal["pending", "processing", "completed", "failed"]

# Step Status Enum for step-by-step execution
class StepStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"

# Log Entry Model
class LogEntry(BaseModel):
    id: str  # Unique identifier for each log entry
    time: str
    message: str
    type: Literal["default", "info", "success", "error"]

# Step State Model for tracking individual step progress
class StepState(BaseModel):
    index: int
    name: str
    title: str  # Display name
    status: StepStatus = StepStatus.PENDING
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None
    artifact_paths: List[str] = []  # Paths to intermediate results
    error_message: Optional[str] = None

# Task State Model
class Task:
    def __init__(self, task_id: str, pdf_filename: str, mode: Literal["auto", "manual"] = "auto"):
        self.id = task_id
        self.mode = mode  # "auto" for full pipeline, "manual" for step-by-step
        self.status: TaskStatus = "pending"
        self.logs: List[LogEntry] = []
        self.current_step = -1
        self.pdf_filename = Path(pdf_filename).name  # Sanitize filename
        self.file_hash: Optional[str] = None  # sha256 of uploaded PDF bytes
        self.expected_pages: Optional[int] = None  # number of pages in uploaded PDF (for progress)
        self.result_images: List[Dict[str, str]] = []
        self.error_message: Optional[str] = None
        self.last_log_index = 0  # For incremental log polling
        self.created_at = datetime.now()
        self.updated_at = datetime.now()

        # File paths (anchored to script directory)
        base_dir = Path(__file__).parent
        self.uploads_dir = base_dir / "uploads"
        self.uploads_dir.mkdir(parents=True, exist_ok=True)

        # Task-scoped workdir to avoid collisions
        self.task_workdir = self.uploads_dir / task_id
        self.task_workdir.mkdir(parents=True, exist_ok=True)

        self.pdf_path = self.task_workdir / self.pdf_filename
        self.exam_dir: Optional[Path] = None  # Will be set after pdf_to_images

        # Initialize step states for step-by-step execution
        self.steps: List[StepState] = [
            StepState(index=0, name="pdf_to_images", title="PDF 转图片"),
            StepState(index=1, name="extract_questions", title="题目提取"),
            StepState(index=2, name="data_analysis", title="资料分析重组"),
            StepState(index=3, name="compose_long_images", title="长图拼接"),
            StepState(index=4, name="collect_results", title="结果汇总"),
        ]

    def add_log(self, message: str, log_type: str = "default"):
        """Add a log entry with timestamp and unique ID"""
        now = datetime.now()
        time_str = now.strftime("%H:%M:%S")
        # Generate unique ID: timestamp (ms) + short UUID
        log_id = f"{int(now.timestamp() * 1000)}-{uuid.uuid4().hex[:8]}"
        self.logs.append(LogEntry(id=log_id, time=time_str, message=message, type=log_type))
        self.updated_at = now

    def get_step(self, step_index: int) -> Optional[StepState]:
        """Get step state by index"""
        if 0 <= step_index < len(self.steps):
            return self.steps[step_index]
        return None

    def mark_step_running(self, step_index: int):
        """Mark a step as running"""
        step = self.get_step(step_index)
        if step:
            step.status = StepStatus.RUNNING
            step.started_at = datetime.now()
            self.current_step = step_index
            self.updated_at = datetime.now()

    def mark_step_completed(self, step_index: int, artifact_paths: Optional[List[str]] = None):
        """Mark a step as completed"""
        step = self.get_step(step_index)
        if step:
            step.status = StepStatus.COMPLETED
            step.ended_at = datetime.now()
            if artifact_paths:
                step.artifact_paths = artifact_paths
            self.updated_at = datetime.now()

    def mark_step_failed(self, step_index: int, error: str):
        """Mark a step as failed"""
        step = self.get_step(step_index)
        if step:
            step.status = StepStatus.FAILED
            step.ended_at = datetime.now()
            step.error_message = error
            self.updated_at = datetime.now()

    def can_run_step(self, step_index: int) -> tuple[bool, Optional[str]]:
        """
        Check if a step can be run.
        Returns (can_run, error_message)
        """
        if step_index < 0 or step_index >= len(self.steps):
            return False, f"Invalid step index: {step_index}"

        step = self.steps[step_index]

        # Allow retry for failed steps
        if step.status == StepStatus.COMPLETED:
            return False, f"步骤 {step.title} 已经完成"

        # Check if step is currently running (not same step)
        if step.status == StepStatus.RUNNING:
            return False, f"步骤 {step.title} 正在运行中"

        # Check if previous steps are completed (dependency check)
        if step_index > 0:
            prev_step = self.steps[step_index - 1]
            if prev_step.status not in [StepStatus.COMPLETED, StepStatus.SKIPPED]:
                return False, f"请先完成步骤 {prev_step.title}"

        # Check if another step is currently running
        if self.current_step >= 0 and self.current_step != step_index:
            running_step = self.steps[self.current_step]
            return False, f"步骤 {running_step.title} 正在运行中，请等待完成"

        return True, None

    def reset_step(self, step_index: int):
        """Reset a step to pending state (for retry)"""
        step = self.get_step(step_index)
        if step and step.status == StepStatus.FAILED:
            step.status = StepStatus.PENDING
            step.error_message = None
            step.started_at = None
            step.ended_at = None
            self.updated_at = datetime.now()

# Global task storage (in-memory, can be upgraded to Redis/SQLite)
TASKS: Dict[str, Task] = {}

# Task execution locks to prevent concurrent step execution
TASK_LOCKS: Dict[str, asyncio.Lock] = {}

def get_task_lock(task_id: str) -> asyncio.Lock:
    """Get or create a lock for a specific task"""
    if task_id not in TASK_LOCKS:
        TASK_LOCKS[task_id] = asyncio.Lock()
    return TASK_LOCKS[task_id]


# Exam directory locks to prevent concurrent PDF->images conversion for same file
EXAM_LOCKS: Dict[str, asyncio.Lock] = {}


def get_exam_lock(exam_key: str) -> asyncio.Lock:
    """Get or create a lock for a specific exam_dir key (usually file hash)."""
    if exam_key not in EXAM_LOCKS:
        EXAM_LOCKS[exam_key] = asyncio.Lock()
    return EXAM_LOCKS[exam_key]


def resolve_exam_dir(
    project_root: Path,
    clean_name: str,
    file_hash: Optional[str],
    original_filename: Optional[str] = None,
) -> tuple[Path, str]:
    """
    基于 PDF 内容 hash 解析稳定的试卷目录。

    新规则：
      - 目录名格式："{clean_name}__{hash前8位}"
      - 相同完整hash -> 复用同一目录
      - 相同clean_name但hash不同 -> 不同目录

    同时会自动创建/更新 job_meta.json 用于显式状态跟踪。
    """
    base_dir = project_root / "pdf_images"

    exam_dir, exam_dir_name = resolve_exam_dir_by_hash(
        clean_name=clean_name, file_hash=file_hash, base_dir=base_dir
    )

    # 创建/更新 job_meta.json
    if file_hash:
        meta = {}
        meta_existed = False
        try:
            meta = load_job_meta(exam_dir)
            meta_existed = bool(meta)
        except json.JSONDecodeError:
            # JSON格式错误，保留旧文件，只更新关键字段
            meta = {}
        except FileNotFoundError:
            meta = {}

        now_iso = datetime.now().isoformat(timespec="seconds")
        if not meta:
            # 新任务或文件不存在
            meta = {
                "display_name": clean_name,
                "original_filename": original_filename or "",
                "source_sha256": file_hash,
                "created_at": now_iso,
                "pipeline_version": "2.0.0",
                "steps": [],
            }
        else:
            # 已有任务，补充缺失字段
            meta.setdefault("display_name", clean_name)
            if original_filename:
                meta.setdefault("original_filename", original_filename)
            meta.setdefault("source_sha256", file_hash)
            meta.setdefault("created_at", now_iso)
            meta.setdefault("pipeline_version", "2.0.0")
            meta.setdefault("steps", [])

        try:
            save_job_meta(exam_dir, meta)
        except Exception:
            pass

        # 兼容：同时写入 .source_hash 文件
        try:
            (exam_dir / ".source_hash").write_text(file_hash, encoding="utf-8")
        except Exception:
            pass

    return exam_dir, exam_dir_name


def infer_steps_from_disk(exam_dir: Path, expected_pages: Optional[int] = None) -> List[StepState]:
    """
    Infer step completion states from existing artifacts on disk.

    This is used for "resume" mode: if a PDF has been processed before,
    mark finished steps as completed so auto/manual can continue.
    """
    steps: List[StepState] = [
        StepState(index=0, name="pdf_to_images", title="PDF 转图片"),
        StepState(index=1, name="extract_questions", title="题目提取"),
        StepState(index=2, name="data_analysis", title="资料分析重组"),
        StepState(index=3, name="compose_long_images", title="长图拼接"),
        StepState(index=4, name="collect_results", title="结果汇总"),
    ]

    if not exam_dir.is_dir():
        return steps

    page_imgs = sorted(exam_dir.glob("page_*.png"))
    if page_imgs and (expected_pages is None or len(page_imgs) >= expected_pages):
        steps[0].status = StepStatus.COMPLETED
        steps[0].artifact_paths = [str(p) for p in page_imgs]

    q_dirs = [d for d in exam_dir.glob("questions_page_*") if d.is_dir()]
    if any((d / "meta.json").is_file() for d in q_dirs):
        steps[1].status = StepStatus.COMPLETED
        q_imgs: List[str] = []
        for d in q_dirs:
            q_imgs.extend([str(p) for p in d.glob("q*.png")])
        steps[1].artifact_paths = q_imgs

    da_files = [str(p) for p in exam_dir.glob("**/data_analysis_*.png")]
    if da_files:
        steps[2].status = StepStatus.COMPLETED
        steps[2].artifact_paths = da_files

    long_files = [str(p) for p in exam_dir.glob("**/*_long.png")]
    if long_files:
        steps[3].status = StepStatus.COMPLETED
        steps[3].artifact_paths = long_files

    all_q_dir = exam_dir / "all_questions"
    if all_q_dir.is_dir():
        all_q_imgs = [str(p) for p in all_q_dir.glob("*.png")]
        if all_q_imgs:
            steps[4].status = StepStatus.COMPLETED
            steps[4].artifact_paths = all_q_imgs

    # If later steps exist, infer middle steps even if they produced no artifacts
    if steps[4].status == StepStatus.COMPLETED or steps[3].status == StepStatus.COMPLETED:
        if steps[2].status == StepStatus.PENDING:
            steps[2].status = StepStatus.COMPLETED
        if steps[1].status == StepStatus.PENDING:
            steps[1].status = StepStatus.COMPLETED

    # Enforce monotonic dependencies: once a step is pending, later steps are pending
    for i in range(1, len(steps)):
        if steps[i - 1].status != StepStatus.COMPLETED:
            steps[i].status = StepStatus.PENDING
            steps[i].artifact_paths = []

    return steps

# Initialize FastAPI app
app = FastAPI(title="智能试卷处理系统API", version="1.0.0")

# Mount static files and templates (only static directory for security)
templates_dir = Path(__file__).parent / "templates"
static_dir = Path(__file__).parent / "static"
static_dir.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=static_dir), name="static")


# ==================== Helper Functions ====================

async def run_subprocess(
    cmd: List[str],
    task: Task,
    step_name: str,
    cwd: Optional[Path] = None
) -> bool:
    """
    Execute a subprocess command and stream output to task logs.

    Args:
        cmd: Command list to execute
        task: Task object to update
        step_name: Name of the step for logging
        cwd: Working directory for the command

    Returns:
        True if successful, False if failed
    """
    task.add_log(f"开始 {step_name}...", "info")

    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=str(cwd) if cwd else None
        )

        # Stream output line by line
        if process.stdout:
            async for raw_line in process.stdout:
                line = raw_line.decode(errors="replace").strip()
                if line:  # Only log non-empty lines
                    task.add_log(line, "default")

        # Wait for completion
        return_code = await process.wait()

        if return_code == 0:
            task.add_log(f"✓ {step_name} 完成", "success")
            return True
        else:
            task.add_log(f"✗ {step_name} 失败 (exit code: {return_code})", "error")
            return False

    except Exception as e:
        task.add_log(f"✗ {step_name} 出错: {str(e)}", "error")
        return False


async def run_subprocess_safe(
    cmd: List[str],
    task: Task,
    step_name: str,
    cwd: Optional[Path] = None,
) -> bool:
    """
    Execute a subprocess command and stream output to task logs.

    Windows 下 asyncio.create_subprocess_exec 偶发 WinError 5（Access is denied）
    时，自动回退到 subprocess.Popen + to_thread 的兼容模式。
    """
    task.add_log(f"开始 {step_name}...", "info")

    def _format_err(exc: BaseException) -> str:
        text = str(exc)
        return text if text else repr(exc)

    async def _run_with_popen() -> int:
        import subprocess

        def _blocking_run() -> int:
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                cwd=str(cwd) if cwd else None,
            )
            if process.stdout:
                for raw_line in process.stdout:
                    line = raw_line.decode(errors="replace").strip()
                    if line:
                        task.add_log(line, "default")
            return process.wait()

        return await asyncio.to_thread(_blocking_run)

    async def _run_inprocess_python() -> int:
        """
        Final fallback: run python script in-process.

        This avoids Windows security blocks that prevent spawning child processes.
        Only supports commands shaped like: [python, script.py, ...args]
        """
        if len(cmd) < 2:
            raise RuntimeError("empty cmd for in-process run")

        script = Path(cmd[1])
        script_path = script
        if not script.is_absolute():
            base = cwd if cwd else Path.cwd()
            script_path = (base / script).resolve()

        if script_path.suffix.lower() != ".py" or not script_path.is_file():
            raise RuntimeError(f"unsupported in-process script: {script_path}")

        import contextlib
        import io
        import os
        import runpy

        def _blocking() -> tuple[int, str]:
            buf = io.StringIO()
            old_argv = sys.argv[:]
            old_cwd = os.getcwd()
            try:
                if cwd:
                    os.chdir(str(cwd))
                sys.argv = [str(script_path), *cmd[2:]]
                with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                    try:
                        runpy.run_path(str(script_path), run_name="__main__")
                        code = 0
                    except SystemExit as se:
                        code = int(se.code) if isinstance(se.code, int) else 1
            finally:
                sys.argv = old_argv
                os.chdir(old_cwd)
            return code, buf.getvalue()

        code, output = await asyncio.to_thread(_blocking)
        for line in output.splitlines():
            line = line.strip()
            if line:
                task.add_log(line, "default")
        return code

    def _is_access_denied(exc: BaseException) -> bool:
        winerr = getattr(exc, "winerror", None)
        if winerr in (5, 740):
            return True
        errno_val = getattr(exc, "errno", None)
        if errno_val in (13,):
            return True
        msg = str(exc)
        return any(
            needle in msg
            for needle in ("Access is denied", "Permission denied", "拒绝访问")
        )

    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=str(cwd) if cwd else None,
        )

        if process.stdout:
            async for raw_line in process.stdout:
                line = raw_line.decode(errors="replace").strip()
                if line:
                    task.add_log(line, "default")

        return_code = await process.wait()

    except (OSError, NotImplementedError) as e:
        # NotImplementedError: current event loop doesn't support subprocesses
        if isinstance(e, NotImplementedError) or _is_access_denied(e):
            try:
                if isinstance(e, NotImplementedError):
                    task.add_log("当前事件循环不支持子进程，尝试兼容子进程模式运行…", "info")
                else:
                    task.add_log("检测到 WinError 5，尝试兼容子进程模式运行…", "info")
                return_code = await _run_with_popen()
            except OSError as inner:
                if _is_access_denied(inner):
                    task.add_log("兼容子进程仍被拒绝，改为进程内运行脚本…", "info")
                    try:
                        return_code = await _run_inprocess_python()
                    except Exception as inner2:
                        task.add_log(f"? {step_name} 出错: {_format_err(inner2)}", "error")
                        return False
                else:
                    task.add_log(f"? {step_name} 出错: {_format_err(inner)}", "error")
                    return False
            except Exception as inner:
                task.add_log(f"? {step_name} 出错: {_format_err(inner)}", "error")
                return False
        else:
            task.add_log(f"? {step_name} 出错: {_format_err(e)}", "error")
            return False
    except Exception as e:
        task.add_log(f"? {step_name} 出错: {_format_err(e)}", "error")
        return False

    if return_code == 0:
        task.add_log(f"? {step_name} 完成", "success")
        return True
    task.add_log(f"? {step_name} 失败 (exit code: {return_code})", "error")
    return False


# ==================== Step Execution Functions ====================

def cleanup_step_artifacts(task: Task, step_index: int):
    """
    Clean up artifacts from a specific step and all dependent steps.

    Step dependencies:
    - Step 0 (PDF to images): Affects all steps
    - Step 1 (Extract questions): Affects steps 2, 3, 4
    - Step 2 (Data analysis): Affects step 4
    - Step 3 (Compose long images): Affects step 4
    - Step 4 (Collect results): Only affects itself
    """
    if not task.exam_dir or not task.exam_dir.exists():
        return

    import shutil

    task.add_log(f"清理步骤 {step_index} 的旧数据...", "info")

    try:
        if step_index == 0:
            # 仅清理派生结果，保留 page_*.png 和元数据以便同一PDF复用
            task.add_log("  删除旧的派生输出(保留原始页图和元数据)", "default")
            for item in task.exam_dir.iterdir():
                if item.is_dir():
                    shutil.rmtree(item)
                    continue
                # 保留的文件：.source_hash, job_meta.json, page_*.png
                if item.name in (".source_hash", "job_meta.json"):
                    continue
                if item.name.startswith("page_") and item.suffix.lower() == ".png":
                    continue
                item.unlink()

        elif step_index == 1:
            # Clean questions_page_* directories and all_questions
            for questions_dir in task.exam_dir.glob("questions_page_*"):
                task.add_log(f"  删除 {questions_dir.name}/", "default")
                shutil.rmtree(questions_dir)

            all_questions = task.exam_dir / "all_questions"
            if all_questions.exists():
                task.add_log("  删除 all_questions/", "default")
                shutil.rmtree(all_questions)

        elif step_index == 2:
            # Clean data_analysis_*.png files and all_questions
            for da_file in task.exam_dir.glob("**/data_analysis_*.png"):
                task.add_log(f"  删除 {da_file.relative_to(task.exam_dir)}", "default")
                da_file.unlink()

            all_questions = task.exam_dir / "all_questions"
            if all_questions.exists():
                task.add_log("  删除 all_questions/", "default")
                shutil.rmtree(all_questions)

        elif step_index == 3:
            # Clean *_long.png files and all_questions
            for long_file in task.exam_dir.glob("**/*_long.png"):
                task.add_log(f"  删除 {long_file.relative_to(task.exam_dir)}", "default")
                long_file.unlink()

            all_questions = task.exam_dir / "all_questions"
            if all_questions.exists():
                task.add_log("  删除 all_questions/", "default")
                shutil.rmtree(all_questions)

        elif step_index == 4:
            # Clean all_questions directory only
            all_questions = task.exam_dir / "all_questions"
            if all_questions.exists():
                task.add_log("  删除 all_questions/", "default")
                shutil.rmtree(all_questions)

        task.add_log("✓ 旧数据清理完成", "success")

    except Exception as e:
        task.add_log(f"清理旧数据时出错: {str(e)}", "error")


async def run_step_0_pdf_to_images(task: Task) -> bool:
    """
    Step 0: Convert PDF to images
    Returns True on success, False on failure
    """
    import re
    project_root = PROJECT_ROOT

    # Clean previous artifacts if retrying
    step = task.get_step(0)
    if step and step.status in [StepStatus.FAILED, StepStatus.COMPLETED]:
        cleanup_step_artifacts(task, 0)

    task.mark_step_running(0)
    task.add_log("正在转换PDF为图片...", "info")

    try:
        # 使用与pdf_to_images.py相同的clean_filename逻辑
        pdf_stem = Path(task.pdf_filename).stem
        clean_name = re.sub(r'[^\w\u4e00-\u9fa5]+', '_', pdf_stem).strip('_')

        # 基于文件内容 hash 生成稳定目录名（同一份 PDF 复用 page_*.png）
        file_hash = task.file_hash
        if not file_hash:
            try:
                file_hash = hashlib.sha256(task.pdf_path.read_bytes()).hexdigest()
                task.file_hash = file_hash
            except Exception:
                file_hash = None

        # 用友好目录名解析试卷目录；同名任务用锁避免并发冲突
        exam_lock = get_exam_lock(clean_name)
        async with exam_lock:
            task.exam_dir, exam_dir_name = resolve_exam_dir(
                project_root, clean_name, file_hash, original_filename=task.pdf_filename
            )
            import fitz
            doc = fitz.open(task.pdf_path)
            total_pages = len(doc)

            def _page_sort_key(p: Path) -> int:
                try:
                    return int(p.stem.split("_", 1)[1])
                except Exception:
                    return 0

            existing_imgs = sorted(task.exam_dir.glob("page_*.png"), key=_page_sort_key)
            if existing_imgs and len(existing_imgs) >= total_pages:
                artifact_paths = [str(p) for p in existing_imgs[:total_pages]]
                task.add_log(
                    f"检测到已存在 {len(existing_imgs)} 页图片，跳过PDF转图片。",
                    "success",
                )
            else:
                artifact_paths = []
                for page_num in range(total_pages):
                    page = doc[page_num]
                    pix = page.get_pixmap(dpi=300)
                    img_name = f"page_{page_num + 1}.png"
                    img_path = task.exam_dir / img_name
                    pix.save(str(img_path))
                    artifact_paths.append(str(img_path))
                    task.add_log(
                        f"  转换第 {page_num + 1}/{total_pages} 页", "default"
                    )
                task.add_log(f"✓ PDF转图片完成，共 {total_pages} 页", "success")

            doc.close()

        # 写入.last_processed标记文件
        last_processed_file = project_root / "pdf_images" / ".last_processed"
        last_processed_file.write_text(exam_dir_name, encoding="utf-8")

        task.mark_step_completed(0, artifact_paths)
        return True

    except Exception as e:
        error_msg = f"PDF转图片失败: {str(e)}"
        task.mark_step_failed(0, error_msg)
        task.add_log(f"✗ {error_msg}", "error")
        return False


async def run_step_1_extract_questions(task: Task) -> bool:
    """
    Step 1: Extract and split questions from pages
    Returns True on success, False on failure
    """
    project_root = Path(__file__).parent.parent
    python_exe = sys.executable

    # Clean previous artifacts if retrying
    step = task.get_step(1)
    if step and step.status in [StepStatus.FAILED, StepStatus.COMPLETED]:
        cleanup_step_artifacts(task, 1)

    task.mark_step_running(1)

    success = await run_subprocess_safe(
        [python_exe, "extract_questions_ppstruct.py", "--dir", str(task.exam_dir)],
        task,
        "题目提取",
        cwd=project_root
    )

    if success:
        # Collect artifact paths
        artifact_paths = []
        if task.exam_dir:
            for questions_dir in task.exam_dir.glob("questions_page_*"):
                artifact_paths.extend([str(p) for p in questions_dir.glob("*.png")])
        task.mark_step_completed(1, artifact_paths)
    else:
        task.mark_step_failed(1, "题目提取失败")

    return success


async def run_step_2_data_analysis(task: Task) -> bool:
    """
    Step 2: Process data analysis questions (may not exist in all exams)
    Returns True on success, False on failure (non-fatal)
    """
    project_root = Path(__file__).parent.parent
    python_exe = sys.executable

    # Clean previous artifacts if retrying
    step = task.get_step(2)
    if step and step.status in [StepStatus.FAILED, StepStatus.COMPLETED]:
        cleanup_step_artifacts(task, 2)

    task.mark_step_running(2)

    success = await run_subprocess_safe(
        [python_exe, "make_data_analysis_big.py", "--dir", str(task.exam_dir)],
        task,
        "资料分析重组",
        cwd=project_root
    )

    if success:
        # Collect data analysis artifacts
        artifact_paths = []
        if task.exam_dir:
            for da_file in task.exam_dir.glob("**/data_analysis_*.png"):
                artifact_paths.append(str(da_file))
        task.mark_step_completed(2, artifact_paths)
        return True
    else:
        # 资料分析可能不存在，不算致命错误
        task.add_log("注意: 资料分析处理失败或不存在相关题目", "info")
        task.mark_step_completed(2, [])  # Mark as completed even if no data analysis found
        return True


async def run_step_3_compose_long_images(task: Task) -> bool:
    """
    Step 3: Compose long images from question parts
    Returns True on success, False on failure (non-fatal)
    """
    project_root = Path(__file__).parent.parent
    python_exe = sys.executable

    # Clean previous artifacts if retrying
    step = task.get_step(3)
    if step and step.status in [StepStatus.FAILED, StepStatus.COMPLETED]:
        cleanup_step_artifacts(task, 3)

    task.mark_step_running(3)

    success = await run_subprocess_safe(
        [python_exe, "compose_question_long_image.py", "--dir", str(task.exam_dir)],
        task,
        "长图拼接",
        cwd=project_root
    )

    if success:
        # Collect long image artifacts
        artifact_paths = []
        if task.exam_dir:
            for long_img in task.exam_dir.glob("**/*_long.png"):
                artifact_paths.append(str(long_img))
        task.mark_step_completed(3, artifact_paths)
        return True
    else:
        task.add_log("注意: 长图拼接失败", "info")
        task.mark_step_completed(3, [])  # Mark as completed even if composing failed
        return True


async def run_step_4_collect_results(task: Task) -> bool:
    """
    Step 4: Collect all question images into final directory
    Returns True on success, False on failure
    """
    project_root = Path(__file__).parent.parent

    # Clean previous artifacts if retrying
    step = task.get_step(4)
    if step and step.status in [StepStatus.FAILED, StepStatus.COMPLETED]:
        cleanup_step_artifacts(task, 4)

    task.mark_step_running(4)
    task.add_log("开始汇总结果...", "info")

    try:
        # 调用与cli_menu.py相同的汇总逻辑
        import json
        import shutil

        from src.common import iter_meta_paths, resolve_image_path

        img_dir = task.exam_dir
        if not img_dir:
            raise RuntimeError("exam_dir is not set")

        all_dir = img_dir / "all_questions"
        if all_dir.exists():
            shutil.rmtree(all_dir, ignore_errors=True)
        all_dir.mkdir(parents=True, exist_ok=True)

        meta_paths = iter_meta_paths(img_dir)
        if not meta_paths:
            task.add_log("未找到 questions_page_*/meta.json，跳过汇总。", "info")
        else:
            metas = []
            qnos_to_skip = set()
            for meta_path in meta_paths:
                with meta_path.open("r", encoding="utf-8") as f:
                    meta = json.load(f)
                metas.append(meta)
                for bq in meta.get("big_questions", []):
                    for qno in bq.get("qnos", []):
                        if isinstance(qno, int):
                            qnos_to_skip.add(qno)

            used_names: set[str] = set()

            def copy_with_unique_name(src: Path, base_name: str) -> None:
                name = base_name
                stem = Path(base_name).stem
                suffix = Path(base_name).suffix or ".png"
                idx = 2
                while name in used_names:
                    name = f"{stem}_{idx}{suffix}"
                    idx += 1
                used_names.add(name)
                shutil.copy2(src, all_dir / name)

            for meta in metas:
                for q in meta.get("questions", []):
                    qno = q.get("qno")
                    if isinstance(qno, int) and qno in qnos_to_skip:
                        continue

                    img_path_str = q.get("long_image") or q.get("image")
                    if not img_path_str:
                        continue

                    src = resolve_image_path(str(img_path_str), img_dir.parent)
                    if not src.is_file():
                        continue

                    base_name = src.name if qno is None else f"q{qno}.png"
                    copy_with_unique_name(src, base_name)

                for bq in meta.get("big_questions", []):
                    combined = bq.get("combined_image")
                    if not combined:
                        continue

                    src = resolve_image_path(str(combined), img_dir.parent)
                    if not src.is_file():
                        continue

                    bid = str(bq.get("id") or "big_question")
                    base_name = f"{bid}.png"
                    copy_with_unique_name(src, base_name)
        task.add_log("✓ 题目图片汇总完成", "success")

        # 查找all_questions目录下的所有图片
        all_questions_dir = task.exam_dir / "all_questions"
        artifact_paths = []

        if all_questions_dir.exists():
            image_files = sorted(all_questions_dir.glob("*.png"))
            task.result_images = [
                {
                    "name": img.name,
                    "filename": img.name,
                    "path": str(img.relative_to(project_root))
                }
                for img in image_files
            ]
            artifact_paths = [str(img) for img in image_files]
            task.add_log(f"✓ 找到 {len(task.result_images)} 张题目图片", "success")
        else:
            task.add_log("警告: 未找到all_questions目录", "info")

        task.mark_step_completed(4, artifact_paths)
        return True

    except Exception as e:
        error_msg = f"汇总时出现问题 - {str(e)}"
        task.mark_step_failed(4, error_msg)
        task.add_log(f"✗ {error_msg}", "error")
        return False


# Map of step index to execution function
STEP_RUNNERS = [
    run_step_0_pdf_to_images,
    run_step_1_extract_questions,
    run_step_2_data_analysis,
    run_step_3_compose_long_images,
    run_step_4_collect_results,
]


async def run_single_step(task_id: str, step_index: int):
    """
    Execute a single step for manual mode.
    This runs in the background using asyncio.create_task.
    """
    task = TASKS.get(task_id)
    if not task:
        return

    # Acquire lock to prevent concurrent execution
    lock = get_task_lock(task_id)
    async with lock:
        # Re-validate step can be run (in case state changed while waiting for lock)
        can_run, error_msg = task.can_run_step(step_index)
        if not can_run:
            task.add_log(f"无法运行步骤: {error_msg}", "error")
            return

        task.status = "processing"

        try:
            # Execute the step
            success = await STEP_RUNNERS[step_index](task)

            if not success and step_index in [0, 1, 4]:  # Critical steps
                task.status = "failed"
                task.error_message = f"步骤 {step_index} 失败"
                task.current_step = -1
                return

            # Check if all steps are completed
            all_completed = all(step.status == StepStatus.COMPLETED for step in task.steps)
            if all_completed:
                task.status = "completed"
                task.current_step = -1
                task.add_log("🎉 所有处理步骤完成!", "success")
            else:
                task.status = "pending"  # Ready for next step
                task.current_step = -1

        except Exception as e:
            task.status = "failed"
            task.error_message = str(e)
            task.current_step = -1
            task.add_log(f"步骤执行失败: {str(e)}", "error")


async def process_pipeline(task_id: str):
    """
    Execute the full processing pipeline for a task (auto mode).
    This runs in the background using asyncio.create_task.
    Maintains backward compatibility with original implementation.
    """
    task = TASKS.get(task_id)
    if not task:
        return

    task.status = "processing"
    task.add_log("Pipeline started", "info")

    try:
        # Execute all steps in sequence
        for step_index in range(len(STEP_RUNNERS)):
            step_state = task.get_step(step_index)
            if step_state and step_state.status == StepStatus.COMPLETED:
                task.add_log(
                    f"跳过步骤 {step_index + 1}: {step_state.title}（已完成）",
                    "info",
                )
                continue

            task.current_step = step_index
            success = await STEP_RUNNERS[step_index](task)

            # For critical steps (0, 1, 4), failure is fatal
            if not success and step_index in [0, 1, 4]:
                raise Exception(f"关键步骤 {step_index} 失败")

        # Mark as completed
        task.status = "completed"
        task.current_step = -1
        task.add_log("🎉 所有处理步骤完成!", "success")

    except Exception as e:
        task.status = "failed"
        task.error_message = str(e)
        task.add_log(f"Pipeline failed: {str(e)}", "error")


# ==================== API Endpoints ====================

@app.get("/", response_class=HTMLResponse)
async def root():
    """Serve the main frontend HTML page"""
    index_path = templates_dir / "index.html"
    if not index_path.exists():
        raise HTTPException(status_code=404, detail="Frontend template not found")
    return HTMLResponse(content=index_path.read_text(encoding="utf-8"))


@app.post("/api/upload")
async def upload_pdf(file: UploadFile = File(...), mode: str = "auto"):
    """
    Upload a PDF file and create a new task.

    Args:
        file: The PDF file to upload
        mode: Execution mode - "auto" for full pipeline, "manual" for step-by-step

    Returns:
        task_id: Unique identifier for this processing task
        mode: The execution mode
        steps: List of available steps
    """
    # Validate file type
    if not file.filename or not file.filename.lower().endswith('.pdf'):
        raise HTTPException(status_code=400, detail="Only PDF files are accepted")

    # Validate mode
    if mode not in ["auto", "manual"]:
        raise HTTPException(status_code=400, detail="Mode must be 'auto' or 'manual'")

    # Create new task with specified mode
    task_id = uuid.uuid4().hex
    task = Task(task_id, file.filename, mode=mode)
    TASKS[task_id] = task

    # Save uploaded PDF
    content = await file.read()
    task.file_hash = hashlib.sha256(content).hexdigest()
    task.pdf_path.write_bytes(content)

    # Resolve exam dir & infer existing step states (resume by default)
    project_root = Path(__file__).parent.parent
    import re

    pdf_stem = Path(task.pdf_filename).stem
    clean_name = re.sub(r"[^\w\u4e00-\u9fa5]+", "_", pdf_stem).strip("_")

    exam_lock = get_exam_lock(clean_name)
    async with exam_lock:
        task.exam_dir, exam_dir_name = resolve_exam_dir(
            project_root, clean_name, task.file_hash, original_filename=task.pdf_filename
        )

    expected_pages: Optional[int] = None
    try:
        import fitz

        doc = fitz.open(task.pdf_path)
        expected_pages = len(doc)
        doc.close()
    except Exception:
        expected_pages = None

    task.expected_pages = expected_pages

    inferred_steps = infer_steps_from_disk(task.exam_dir, expected_pages=expected_pages)
    for idx, inferred in enumerate(inferred_steps):
        if idx < len(task.steps):
            task.steps[idx].status = inferred.status
            task.steps[idx].artifact_paths = inferred.artifact_paths
            task.steps[idx].error_message = None

    task.add_log(
        f"文件上传成功: {file.filename} (模式: {mode}, hash: {task.file_hash[:8]})",
        "success",
    )

    return {
        "task_id": task_id,
        "filename": file.filename,
        "mode": mode,
        "steps": [
            {
                "index": step.index,
                "name": step.name,
                "title": step.title,
                "status": step.status.value
            }
            for step in task.steps
        ]
    }


@app.post("/api/process")
async def start_processing(request_body: dict):
    """
    Start processing a task (supports both auto and manual modes).

    For auto mode: Starts the full pipeline automatically.
    For manual mode: This endpoint is not used; use step-specific endpoints instead.

    Request body:
        task_id: The task ID from upload

    Returns:
        message: Confirmation message
        mode: Task execution mode
    """
    task_id = request_body.get("task_id")
    if not task_id:
        raise HTTPException(status_code=400, detail="task_id is required")

    task = TASKS.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    if task.status == "processing":
        return {"message": "Task is already processing", "mode": task.mode}

    # For auto mode, start full pipeline
    if task.mode == "auto":
        asyncio.create_task(process_pipeline(task_id))
        return {"message": "Full pipeline started", "mode": "auto"}
    else:
        # For manual mode, guide user to use step endpoints
        return {
            "message": "Task is in manual mode. Use /api/tasks/{task_id}/steps/{step_index}/start to run individual steps",
            "mode": "manual"
        }


@app.post("/api/tasks/{task_id}/restart/{from_step}")
async def restart_from_step(task_id: str, from_step: int):
    """
    Restart a task from a given step.

    This clears derived artifacts from that step onward (keeping page_*.png),
    resets step statuses to pending, and allows both auto/manual to rerun.
    """
    task = TASKS.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    if from_step < 0 or from_step >= len(task.steps):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid step index: {from_step}. Must be between 0 and {len(task.steps) - 1}",
        )

    if task.status == "processing":
        raise HTTPException(status_code=409, detail="Task is processing, cannot restart")

    lock = get_task_lock(task_id)
    async with lock:
        cleanup_step_artifacts(task, from_step)
        for idx in range(from_step, len(task.steps)):
            step = task.steps[idx]
            step.status = StepStatus.PENDING
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


@app.post("/api/tasks/{task_id}/steps/{step_index}/start")
async def start_step(task_id: str, step_index: int):
    """
    Start execution of a specific step (manual mode).

    Args:
        task_id: Task identifier
        step_index: Index of the step to execute (0-4)

    Returns:
        task_id: Task identifier
        step: Step information
        message: Status message
    """
    task = TASKS.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    # Validate step index bounds
    if step_index < 0 or step_index >= len(task.steps):
        raise HTTPException(status_code=400, detail=f"Invalid step index: {step_index}. Must be between 0 and {len(task.steps) - 1}")

    # Enforce manual mode only
    if task.mode != "manual":
        raise HTTPException(
            status_code=409,
            detail=f"Task is in {task.mode} mode. Manual step execution is only available for manual mode tasks."
        )

    # Check if task is already processing in auto mode
    if task.status == "processing" and task.current_step != -1:
        raise HTTPException(
            status_code=409,
            detail=f"Task is currently processing step {task.current_step}. Cannot start manual step."
        )

    # Reset step if it's failed (for retry)
    if task.steps[step_index].status == StepStatus.FAILED:
        task.reset_step(step_index)

    # Check if step can be run
    can_run, error_msg = task.can_run_step(step_index)
    if not can_run:
        raise HTTPException(status_code=409, detail=error_msg)

    # Start step execution in background
    asyncio.create_task(run_single_step(task_id, step_index))

    step = task.steps[step_index]
    return {
        "task_id": task_id,
        "step": {
            "index": step.index,
            "name": step.name,
            "title": step.title,
            "status": step.status.value
        },
        "message": f"步骤 {step.title} 已开始执行"
    }


@app.get("/api/tasks/{task_id}/steps/{step_index}/results")
async def get_step_results(task_id: str, step_index: int):
    """
    Get results (artifacts) from a specific step.

    Args:
        task_id: Task identifier
        step_index: Index of the step

    Returns:
        step: Step information including artifact paths
    """
    task = TASKS.get(task_id)
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
            "artifacts": step.artifact_paths[:10],  # Return first 10 artifacts
            "error": step.error_message
        }
    }


@app.get("/api/status/{task_id}")
async def get_status(task_id: str, since: int = 0):
    """
    Get current status and logs for a task.
    Now includes step-by-step status information.

    Args:
        since: Return only logs after this index (for incremental polling)

    Returns:
        status: Current task status (pending/processing/completed/failed)
        mode: Execution mode (auto/manual)
        current_step: Current processing step index
        steps: Detailed status of all steps
        logs: List of new log entries since last poll
        total_logs: Total number of logs (for cursor tracking)
    """
    task = TASKS.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    # Return only new logs since the requested index
    # Add fallback ID for any logs that don't have one (e.g., from old tasks)
    new_logs = []
    for idx, log in enumerate(task.logs[since:], start=since):
        log_id = getattr(log, "id", None) or f"{task_id}-{idx}"
        entry = log.dict()
        entry["id"] = log_id
        new_logs.append(entry)

    total_pages = task.expected_pages
    if (total_pages is None or total_pages == 0) and task.exam_dir:
        try:
            total_pages = len(list(task.exam_dir.glob("page_*.png")))
        except Exception:
            total_pages = None

    def _step_progress(step_idx: int) -> tuple[Optional[float], Optional[str]]:
        if not total_pages or not task.exam_dir:
            return None, None
        try:
            if step_idx == 0:
                done = len(list(task.exam_dir.glob("page_*.png")))
            elif step_idx == 1:
                done = len(list(task.exam_dir.glob("questions_page_*/meta.json")))
            else:
                return None, None
            progress = min(done / total_pages, 1.0)
            return progress, f"{done}/{total_pages}页"
        except Exception:
            return None, None

    progress_map: Dict[int, tuple[Optional[float], Optional[str]]] = {
        s.index: _step_progress(s.index) for s in task.steps
    }

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
                "started_at": step.started_at.isoformat() if step.started_at else None,
                "ended_at": step.ended_at.isoformat() if step.ended_at else None,
                "artifact_count": len(step.artifact_paths),
                "error": step.error_message,
                "progress": progress_map[step.index][0],
                "progress_text": progress_map[step.index][1],
            }
            for step in task.steps
        ],
        "logs": new_logs,
        "total_logs": len(task.logs),
        "error": task.error_message
    }


@app.get("/api/results/{task_id}")
async def get_results(task_id: str):
    """
    Get the list of generated images for a completed task.

    Returns:
        images: List of image metadata (name, filename, path)
    """
    task = TASKS.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    return {
        "status": task.status,
        "images": task.result_images
    }


@app.get("/api/image/{task_id}/{filename}")
async def serve_image(task_id: str, filename: str):
    """
    Serve an individual result image.

    Args:
        task_id: Task identifier
        filename: Image filename

    Returns:
        Image file
    """
    task = TASKS.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    if not task.exam_dir:
        raise HTTPException(status_code=400, detail="Task not yet processed")

    # Look for image in all_questions directory
    image_path = task.exam_dir / "all_questions" / filename

    if not image_path.exists():
        raise HTTPException(status_code=404, detail="Image not found")

    return FileResponse(image_path, media_type="image/png")


@app.get("/api/download/{task_id}")
async def download_results(task_id: str):
    """
    Download all results as a ZIP file.

    Args:
        task_id: Task identifier

    Returns:
        ZIP file containing all generated images
    """
    task = TASKS.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    if not task.exam_dir:
        raise HTTPException(status_code=400, detail="Task not yet processed")

    all_questions_dir = task.exam_dir / "all_questions"
    if not all_questions_dir.exists():
        raise HTTPException(status_code=404, detail="No results to download")

    # Create ZIP file
    zip_path = task.exam_dir / f"{task_id}_results.zip"
    shutil.make_archive(
        str(zip_path.with_suffix('')),  # base_name without extension
        'zip',
        all_questions_dir
    )

    return FileResponse(
        zip_path,
        media_type="application/zip",
        filename=f"exam_questions_{task_id}.zip"
    )


# ==================== Server Entry Point ====================

if __name__ == "__main__":
    import uvicorn

    print("=" * 60)
    print("智能试卷处理系统 Web 服务")
    print("=" * 60)
    print("\n服务器启动中...")
    print("访问地址: http://localhost:8000")
    print("\n按 Ctrl+C 停止服务器\n")

    uvicorn.run(
        "app:app",
        host="0.0.0.0",
        port=8000,
        reload=True,  # 开发模式下自动重载
        log_level="info"
    )
