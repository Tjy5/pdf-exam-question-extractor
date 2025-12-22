"""
Exams Router - 试卷管理、答案导入、题目图片服务
"""

from pathlib import Path
from typing import Optional, List, Dict, Any
import asyncio
import json
import csv
import io
import re

import base64

from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel

from ...common.types import LEGACY_PDF_IMAGES_DIR
from ...db.connection import get_db_manager
from ...services.answers.answer_pdf_importer import (
    DATA_ANALYSIS_GROUP_SIZE,
    ExamInfo,
    extract_text_from_pdf,
    fold_data_analysis_answers_for_exam,
    is_data_analysis_big_qno,
    match_exam_for_pdf,
    parse_answer_key_text,
)
from ..config import config

router = APIRouter(prefix="/api", tags=["exams"])

# PNG file signature
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


# ==================== Response Models ====================

class ExamOut(BaseModel):
    """试卷输出模型"""
    id: int
    exam_dir_name: str
    display_name: Optional[str] = None
    question_count: int = 0
    has_answers: int = 0
    created_at: str
    processed_at: Optional[str] = None


class QuestionOut(BaseModel):
    """题目输出模型"""
    question_no: int
    question_type: str
    display_label: str  # Friendly display name, e.g., "第1题" or "资料分析第一大题"
    image_url: str
    has_answer: bool = False


class ExamDetailOut(BaseModel):
    """试卷详情输出模型"""
    exam: ExamOut
    questions: List[QuestionOut]


class AnswerImportResult(BaseModel):
    """答案导入结果"""
    imported: int
    skipped: int
    errors: List[str] = []


class AnswerPdfImportFileResult(BaseModel):
    """单个PDF文件导入结果"""
    pdf_filename: str
    matched_exam_id: Optional[int] = None
    matched_exam_dir_name: Optional[str] = None
    match_score: float = 0.0
    extracted_answers: int = 0
    max_question_no: int = 0
    imported: int = 0
    skipped: int = 0
    errors: List[str] = []


class AnswerPdfDirImportRequest(BaseModel):
    """批量导入请求"""
    directory: str = "answer"
    dry_run: bool = False
    max_files: Optional[int] = None
    source: str = "pdf_dir"
    min_match_score: float = 0.62


class AnswerPdfDirImportResult(BaseModel):
    """批量导入结果"""
    files_total: int
    imported_total: int
    skipped_total: int
    results: List[AnswerPdfImportFileResult]


class LocalExamImportRequest(BaseModel):
    """本地试卷目录导入请求"""
    exam_dir_name: str
    display_name: Optional[str] = None
    dry_run: bool = False
    overwrite: bool = False


class LocalExamImportResult(BaseModel):
    """本地试卷目录导入结果"""
    exam_id: Optional[int] = None
    exam_dir_name: str
    display_name: Optional[str] = None
    question_count: int = 0
    data_analysis_count: int = 0
    imported: int = 0
    skipped: int = 0
    warnings: List[str] = []
    errors: List[str] = []


class LocalDirectoriesResponse(BaseModel):
    """本地目录列表响应"""
    directories: List[str]


# ==================== Utility Functions ====================

def _safe_filename(filename: str) -> None:
    """验证文件名安全性"""
    if "/" in filename or "\\" in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")
    if not filename.lower().endswith(".png"):
        raise HTTPException(status_code=400, detail="Only PNG files allowed")


async def _resolve_exam_dir(exam_id: int) -> Path:
    """解析试卷目录"""
    db = get_db_manager()
    async with db.transaction():
        exam = await db.fetch_one(
            "SELECT exam_dir_name FROM exams WHERE id = ?",
            (exam_id,)
        )
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found")

    exam_dir_name = str(exam["exam_dir_name"] or "")
    if not exam_dir_name or "/" in exam_dir_name or "\\" in exam_dir_name:
        raise HTTPException(status_code=500, detail="Invalid exam_dir_name")

    base_dir = LEGACY_PDF_IMAGES_DIR.resolve()
    exam_dir = (base_dir / exam_dir_name).resolve()

    # 防止路径遍历攻击（如 exam_dir_name 包含 ".."）
    try:
        exam_dir.relative_to(base_dir)
    except ValueError:
        raise HTTPException(status_code=403, detail="Access denied")

    if not exam_dir.is_dir():
        raise HTTPException(status_code=404, detail="Exam directory not found")

    return exam_dir


async def _upsert_answers_for_exam(
    exam_id: int,
    answer_map: Dict[int, str],
    *,
    source: str,
    question_count: int = 0,
    errors: Optional[List[str]] = None,
    valid_question_nos: Optional[set[int]] = None,
    cleanup_data_analysis_sub_answers: bool = False,
) -> tuple[int, int, List[str]]:
    """Insert or update answers for an exam."""
    db = get_db_manager()
    imported = 0
    skipped = 0
    errs: List[str] = errors if errors is not None else []
    allowed = {"A", "B", "C", "D", "E"}

    async with db.transaction():
        if cleanup_data_analysis_sub_answers:
            await db.execute(
                "DELETE FROM exam_answers WHERE exam_id = ? AND question_no BETWEEN 111 AND 130",
                (exam_id,),
            )

        for qno in sorted(answer_map.keys()):
            try:
                qno = int(qno)
                if valid_question_nos is not None and qno not in valid_question_nos:
                    skipped += 1
                    continue
                raw = str(answer_map[qno] or "")
                if qno <= 0 or not raw.strip():
                    skipped += 1
                    continue

                # Normal questions: Q1..question_count, single letter
                if not is_data_analysis_big_qno(qno):
                    answer = raw.strip().upper()
                    if len(answer) != 1 or answer not in allowed:
                        skipped += 1
                        continue
                    # Only enforce question_count upper bound when we don't know the exact question set.
                    if valid_question_nos is None and question_count and qno > int(question_count):
                        skipped += 1
                        continue

                # Data analysis big questions: Q1001..Q1004, 5 letters (sub-answers)
                else:
                    letters = re.findall(r"[A-E]", raw.upper())
                    if len(letters) != int(DATA_ANALYSIS_GROUP_SIZE):
                        skipped += 1
                        continue
                    answer = "".join(letters)

                await db.execute(
                    """
                    INSERT INTO exam_answers (exam_id, question_no, answer, source)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(exam_id, question_no) DO UPDATE SET
                        answer = excluded.answer,
                        source = excluded.source,
                        updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                    """,
                    (exam_id, int(qno), answer, source),
                )
                imported += 1
            except Exception as e:
                errs.append(f"Question {qno}: {e}")
                skipped += 1

        if imported > 0:
            await db.execute(
                "UPDATE exams SET has_answers = 1, updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = ?",
                (exam_id,),
            )

    return imported, skipped, errs


async def _scan_local_exam_directory(
    exam_dir: Path,
    *,
    display_name: Optional[str] = None,
) -> Dict[str, Any]:
    """扫描本地试卷目录，提取题目图片和元数据"""
    errors: List[str] = []
    warnings: List[str] = []
    questions: List[Dict[str, Any]] = []

    if not exam_dir.exists() or not exam_dir.is_dir():
        raise HTTPException(status_code=404, detail="Exam directory not found")

    exam_dir_name = exam_dir.name
    if not display_name:
        # 移除末尾的hash后缀 (e.g., "__17531029")
        display_name = re.sub(r"__[a-f0-9]{8}$", "", exam_dir_name)

    all_dir = (exam_dir / "all_questions").resolve()
    if not all_dir.exists() or not all_dir.is_dir():
        raise HTTPException(status_code=400, detail="all_questions directory not found")

    # 防止符号链接攻击
    if all_dir.is_symlink():
        raise HTTPException(status_code=400, detail="Symlinked directories are not allowed")

    # 扫描PNG文件
    normal_candidates: Dict[int, Path] = {}
    data_candidates: Dict[int, Path] = {}

    for p in sorted(all_dir.glob("*.png")):
        # 跳过符号链接文件
        if p.is_symlink():
            warnings.append(f"Skipped symlinked file: {p.name}")
            continue

        # 确保文件在all_dir内
        try:
            p.resolve().relative_to(all_dir)
        except ValueError:
            warnings.append(f"Skipped file outside directory: {p.name}")
            continue

        name = p.name
        # 匹配普通题目 (q1.png, q2.png, ...)
        m = re.match(r"^q(\d+)\.png$", name, flags=re.IGNORECASE)
        if m:
            try:
                qno = int(m.group(1))
            except ValueError:
                warnings.append(f"Invalid question number in {name}")
                continue
            if qno <= 0:
                warnings.append(f"Invalid question number in {name}")
                continue
            # 跳过资料分析子题 (111-130)
            if 111 <= qno <= 130:
                warnings.append(f"Skipped data analysis sub-question: {name}")
                continue
            if qno in normal_candidates:
                warnings.append(f"Duplicate question number: q{qno}")
                continue
            normal_candidates[qno] = p
            continue

        # 匹配资料分析大题 (data_analysis_1.png, ...)
        m = re.match(r"^data_analysis_(\d+)\.png$", name, flags=re.IGNORECASE)
        if m:
            try:
                da_order = int(m.group(1))
            except ValueError:
                warnings.append(f"Invalid data analysis number in {name}")
                continue
            if da_order <= 0:
                warnings.append(f"Invalid data analysis number in {name}")
                continue
            da_qno = 1000 + da_order
            if da_qno in data_candidates:
                warnings.append(f"Duplicate data analysis number: data_analysis_{da_order}")
                continue
            data_candidates[da_qno] = p
            continue

        warnings.append(f"Ignored non-question image: {name}")

    if not normal_candidates and not data_candidates:
        errors.append("No valid question images found in all_questions")

    # 读取summary.json (可选)
    summary_path = all_dir / "summary.json"
    if summary_path.exists():
        try:
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            if isinstance(summary, dict):
                if "normal_questions" in summary and summary["normal_questions"] != len(normal_candidates):
                    warnings.append(f"summary.json normal_questions mismatch: expected {summary['normal_questions']}, found {len(normal_candidates)}")
                if "big_questions" in summary and summary["big_questions"] != len(data_candidates):
                    warnings.append(f"summary.json big_questions mismatch: expected {summary['big_questions']}, found {len(data_candidates)}")
        except Exception as e:
            warnings.append(f"Failed to read summary.json: {e}")

    # 构建题目列表
    for qno in sorted(normal_candidates.keys()):
        questions.append({
            "question_no": qno,
            "question_type": "single",
            "path": normal_candidates[qno],
            "image_filename": normal_candidates[qno].name,
        })
    for qno in sorted(data_candidates.keys()):
        questions.append({
            "question_no": qno,
            "question_type": "data_analysis",
            "path": data_candidates[qno],
            "image_filename": data_candidates[qno].name,
        })

    return {
        "exam_dir_name": exam_dir_name,
        "display_name": display_name,
        "questions": questions,
        "question_count": len(normal_candidates),
        "data_analysis_count": len(data_candidates),
        "warnings": warnings,
        "errors": errors,
    }


async def _import_local_questions(
    scan: Dict[str, Any],
    *,
    overwrite: bool = False,
) -> LocalExamImportResult:
    """将扫描的本地题目导入数据库"""
    from datetime import datetime, timezone

    db = get_db_manager()
    exam_dir_name = scan["exam_dir_name"]
    display_name = scan.get("display_name")
    questions = scan.get("questions", [])
    warnings: List[str] = list(scan.get("warnings") or [])
    errors: List[str] = list(scan.get("errors") or [])

    if not questions:
        raise HTTPException(status_code=400, detail="No valid question images to import")

    def _read_b64(path: Path) -> Optional[str]:
        """读取图片并转为Base64"""
        try:
            # 检查文件大小（限制10MB）
            file_size = path.stat().st_size
            max_size = 10 * 1024 * 1024  # 10MB
            if file_size > max_size:
                errors.append(f"File too large: {path.name} ({file_size} bytes)")
                return None

            raw = path.read_bytes()
        except Exception as e:
            errors.append(f"Failed to read {path.name}: {e}")
            return None
        if not raw.startswith(PNG_SIGNATURE):
            errors.append(f"Invalid PNG signature: {path.name}")
            return None
        try:
            return base64.b64encode(raw).decode("ascii")
        except Exception as e:
            errors.append(f"Failed to encode {path.name}: {e}")
            return None

    imported = 0
    skipped = 0
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")

    async with db.transaction():
        # 检查试卷是否已存在
        existing = await db.fetch_one(
            "SELECT id FROM exams WHERE exam_dir_name = ?",
            (exam_dir_name,),
        )
        if existing and not overwrite:
            raise HTTPException(status_code=409, detail="Exam already exists (set overwrite=true)")

        # 如果overwrite，删除现有题目和答案
        if existing and overwrite:
            await db.execute(
                "DELETE FROM exam_questions WHERE exam_id = ?",
                (int(existing["id"]),),
            )
            await db.execute(
                "DELETE FROM exam_answers WHERE exam_id = ?",
                (int(existing["id"]),),
            )
            await db.execute(
                "UPDATE exams SET has_answers = 0 WHERE id = ?",
                (int(existing["id"]),),
            )

        # 插入或更新试卷记录
        await db.execute(
            """
            INSERT INTO exams (
                exam_dir_name, display_name, question_count,
                created_at, updated_at, processed_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(exam_dir_name) DO UPDATE SET
                display_name = excluded.display_name,
                question_count = excluded.question_count,
                updated_at = excluded.updated_at,
                processed_at = excluded.processed_at
            """,
            (
                exam_dir_name,
                display_name,
                int(scan.get("question_count", 0)),
                now,
                now,
                now,
            ),
        )

        # 获取试卷ID
        exam_row = await db.fetch_one(
            "SELECT id FROM exams WHERE exam_dir_name = ?",
            (exam_dir_name,),
        )
        if not exam_row:
            raise HTTPException(status_code=500, detail="Failed to resolve exam_id")
        exam_id = int(exam_row["id"])

        # 插入题目
        for item in questions:
            path: Path = item["path"]
            image_b64 = await asyncio.to_thread(_read_b64, path)
            if not image_b64:
                skipped += 1
                continue

            try:
                await db.execute(
                    """
                    INSERT INTO exam_questions (
                        exam_id, question_no, question_type, image_filename, image_data, created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(exam_id, question_no) DO UPDATE SET
                        question_type = excluded.question_type,
                        image_filename = excluded.image_filename,
                        image_data = excluded.image_data
                    """,
                    (
                        exam_id,
                        int(item["question_no"]),
                        item["question_type"],
                        item["image_filename"],
                        image_b64,
                        now,
                    ),
                )
                imported += 1
            except Exception as e:
                errors.append(f"Failed to insert Q{item['question_no']}: {e}")
                skipped += 1

    return LocalExamImportResult(
        exam_id=exam_id,
        exam_dir_name=exam_dir_name,
        display_name=display_name,
        question_count=int(scan.get("question_count", 0)),
        data_analysis_count=int(scan.get("data_analysis_count", 0)),
        imported=imported,
        skipped=skipped,
        warnings=warnings,
        errors=errors,
    )


# ==================== API Endpoints ====================

@router.get("/exams", response_model=List[ExamOut])
async def list_exams():
    """获取所有试卷列表"""
    db = get_db_manager()
    async with db.transaction():
        rows = await db.fetch_all(
            """
            SELECT id, exam_dir_name, display_name, question_count, has_answers,
                   created_at, processed_at
            FROM exams
            ORDER BY created_at DESC
            """
        )
    return [ExamOut(**dict(row)) for row in rows]


@router.get("/exams/{exam_id}", response_model=ExamDetailOut)
async def get_exam_detail(exam_id: int):
    """获取试卷详情（含题目列表）"""
    db = get_db_manager()

    async with db.transaction():
        # 获取试卷信息
        exam_row = await db.fetch_one(
            """
            SELECT id, exam_dir_name, display_name, question_count, has_answers,
                   created_at, processed_at
            FROM exams
            WHERE id = ?
            """,
            (exam_id,)
        )
        if not exam_row:
            raise HTTPException(status_code=404, detail="Exam not found")

        exam = ExamOut(**dict(exam_row))

        # 获取题目列表
        question_rows = await db.fetch_all(
            """
            SELECT eq.question_no, eq.question_type, eq.image_filename,
                   CASE WHEN ea.id IS NOT NULL THEN 1 ELSE 0 END as has_answer
            FROM exam_questions eq
            LEFT JOIN exam_answers ea ON eq.exam_id = ea.exam_id AND eq.question_no = ea.question_no
            WHERE eq.exam_id = ?
            ORDER BY eq.question_no
            """,
            (exam_id,)
        )

    # Helper to generate display label
    def _get_display_label(qno: int, qtype: str) -> str:
        if qtype == "data_analysis" or qno > 1000:
            # Convert 1001 -> "第一", 1002 -> "第二", etc.
            da_order = qno - 1000 if qno > 1000 else qno
            chinese_nums = ["一", "二", "三", "四", "五", "六", "七", "八", "九", "十"]
            cn = chinese_nums[da_order - 1] if 1 <= da_order <= 10 else str(da_order)
            return f"资料分析第{cn}大题"
        return f"第{qno}题"

    questions = [
        QuestionOut(
            question_no=row["question_no"],
            question_type=row["question_type"] or "single",
            display_label=_get_display_label(row["question_no"], row["question_type"] or "single"),
            image_url=f"/api/exams/{exam_id}/questions/{row['question_no']}/image",
            has_answer=bool(row["has_answer"])
        )
        for row in question_rows
    ]

    return ExamDetailOut(exam=exam, questions=questions)


PNG_SIGNATURE = b'\x89PNG\r\n\x1a\n'


def _decode_base64_png(image_data: str) -> Optional[bytes]:
    """Decode Base64 image data from database with PNG validation."""
    if not image_data:
        return None
    s = str(image_data).strip()
    if not s:
        return None
    if s.startswith("data:"):
        comma = s.find(",")
        if comma != -1:
            s = s[comma + 1:]
    try:
        decoded = base64.b64decode(s, validate=True)
        if not decoded.startswith(PNG_SIGNATURE):
            return None
        return decoded
    except Exception:
        return None


@router.get("/exams/{exam_id}/questions/{question_no}/image")
async def get_question_image(exam_id: int, question_no: int):
    """获取题目图片（重启安全，基于数据库）"""
    if question_no <= 0:
        raise HTTPException(status_code=400, detail="Invalid question_no")

    db = get_db_manager()

    async with db.transaction():
        # 获取图片文件名和image_data
        question = await db.fetch_one(
            """
            SELECT image_filename, image_data
            FROM exam_questions
            WHERE exam_id = ? AND question_no = ?
            """,
            (exam_id, question_no)
        )
    if not question:
        raise HTTPException(status_code=404, detail="Question not found")

    image_filename = str(question["image_filename"] or "")
    image_data = question["image_data"]
    _safe_filename(image_filename)

    # 解析试卷目录并构建图片路径
    exam_dir = await _resolve_exam_dir(exam_id)
    questions_dir = (exam_dir / "all_questions").resolve()
    image_path = (questions_dir / image_filename).resolve()

    # 安全检查
    try:
        image_path.relative_to(questions_dir)
    except ValueError:
        raise HTTPException(status_code=403, detail="Access denied")

    if not image_path.exists() or not image_path.is_file():
        # Fallback: serve from database if image_data exists
        if image_data:
            png_bytes = _decode_base64_png(str(image_data))
            if not png_bytes:
                raise HTTPException(status_code=500, detail="Invalid image_data in database")
            return Response(content=png_bytes, media_type="image/png")
        raise HTTPException(status_code=404, detail="Image file not found")

    return FileResponse(image_path, media_type="image/png")


@router.post("/exams/{exam_id}/answers:import", response_model=AnswerImportResult)
async def import_answers(
    exam_id: int,
    file: UploadFile = File(...),
    source: str = Form("import")
):
    """
    批量导入标准答案

    支持三种格式：
    - JSON: [{"question_no": 1, "answer": "A"}, ...]
    - CSV: question_no,answer
    - PDF: answer ranges like "1--5 DDCCA"
    """
    db = get_db_manager()

    async with db.transaction():
        exam = await db.fetch_one("SELECT id, question_count FROM exams WHERE id = ?", (exam_id,))
        if not exam:
            raise HTTPException(status_code=404, detail="Exam not found")
        question_count = int(exam["question_count"] or 0)

        # Determine schema from existing questions (more reliable than question_count).
        question_rows = await db.fetch_all(
            "SELECT question_no FROM exam_questions WHERE exam_id = ?",
            (exam_id,),
        )
    valid_qnos = {int(r["question_no"]) for r in question_rows} if question_rows else None
    force_fold = False
    if valid_qnos:
        has_big = any(qno > 1000 for qno in valid_qnos)
        has_sub = any(111 <= qno <= 130 for qno in valid_qnos)
        force_fold = has_big and not has_sub

    try:
        content = await file.read()
    finally:
        await file.close()

    filename = (file.filename or "").lower()
    errors: List[str] = []
    answer_map: Dict[int, str] = {}

    if filename.endswith(".pdf"):
        max_pdf_size = 10 * 1024 * 1024
        if len(content) > max_pdf_size:
            raise HTTPException(status_code=413, detail="PDF too large (max 10MB)")

        try:
            text = await asyncio.to_thread(extract_text_from_pdf, content)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"PDF parse failed: {e}")

        parsed = parse_answer_key_text(text)
        errors.extend(parsed.errors)
        answer_map = parsed.answers

    else:
        max_import_size = 2 * 1024 * 1024
        if len(content) > max_import_size:
            raise HTTPException(status_code=413, detail="File too large (max 2MB)")

        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError:
            raise HTTPException(status_code=400, detail="File must be UTF-8 encoded")

        try:
            if filename.endswith(".json"):
                items = json.loads(text)
                if not isinstance(items, list):
                    raise HTTPException(status_code=400, detail="JSON must be an array")
                for item in items:
                    qno = int(item.get("question_no", 0))
                    ans = str(item.get("answer", "")).strip()
                    if qno in answer_map and answer_map[qno] != ans:
                        errors.append(f"Duplicate Q{qno}: kept {answer_map[qno]}")
                        continue
                    answer_map[qno] = ans

            elif filename.endswith(".csv"):
                reader = csv.DictReader(io.StringIO(text))
                for i, row in enumerate(reader, start=1):
                    try:
                        qno = int(row.get("question_no", 0))
                        ans = str(row.get("answer", "")).strip()
                        if qno in answer_map and answer_map[qno] != ans:
                            errors.append(f"CSV line {i}: duplicate Q{qno}")
                            continue
                        answer_map[qno] = ans
                    except (ValueError, TypeError, KeyError) as e:
                        errors.append(f"CSV line {i}: {e}")

            else:
                raise HTTPException(status_code=400, detail="Unsupported file type (use .json, .csv, or .pdf)")

        except (json.JSONDecodeError, csv.Error) as e:
            raise HTTPException(status_code=400, detail=f"Parse error: {e}")

    folded_map, fold_errors = fold_data_analysis_answers_for_exam(
        answer_map,
        question_count=question_count,
        force=force_fold,
    )
    errors.extend(fold_errors)

    if valid_qnos:
        folded_map = {int(qno): ans for qno, ans in folded_map.items() if int(qno) in valid_qnos}

    imported, skipped, errors = await _upsert_answers_for_exam(
        exam_id,
        folded_map,
        source=source,
        question_count=question_count,
        errors=errors,
        valid_question_nos=valid_qnos,
        cleanup_data_analysis_sub_answers=force_fold,
    )
    return AnswerImportResult(imported=imported, skipped=skipped, errors=errors[:10])


@router.get("/exams/{exam_id}/answers")
async def get_answers(exam_id: int) -> Dict[str, str]:
    """获取试卷的所有答案"""
    db = get_db_manager()

    async with db.transaction():
        rows = await db.fetch_all(
            """
            SELECT question_no, answer
            FROM exam_answers
            WHERE exam_id = ?
            ORDER BY question_no
            """,
            (exam_id,)
        )

    return {str(row["question_no"]): row["answer"] for row in rows}


@router.post("/exams/answers:import-pdfs", response_model=AnswerPdfDirImportResult)
async def import_answers_from_pdf_dir(req: AnswerPdfDirImportRequest):
    """
    批量导入服务器端answer目录中的PDF答案

    自动匹配PDF文件名到数据库中的试卷，并导入答案。
    """
    db = get_db_manager()

    base = config.project_root.resolve()
    answer_dir = (base / req.directory).resolve()
    try:
        answer_dir.relative_to(base)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid directory (path traversal)")

    if not answer_dir.exists() or not answer_dir.is_dir():
        raise HTTPException(status_code=404, detail=f"Directory not found: {req.directory}")

    pdf_files = sorted([p for p in answer_dir.iterdir() if p.is_file() and p.suffix.lower() == ".pdf"])
    if req.max_files:
        pdf_files = pdf_files[: int(req.max_files)]

    async with db.transaction():
        exam_rows = await db.fetch_all(
            "SELECT id, exam_dir_name, display_name, question_count FROM exams ORDER BY id",
            (),
        )
    exams = [
        ExamInfo(
            id=int(r["id"]),
            exam_dir_name=str(r["exam_dir_name"] or ""),
            display_name=str(r["display_name"]) if r["display_name"] is not None else None,
            question_count=int(r["question_count"] or 0),
        )
        for r in exam_rows
    ]

    imported_total = 0
    skipped_total = 0
    results: List[AnswerPdfImportFileResult] = []

    for pdf_path in pdf_files:
        file_errors: List[str] = []
        try:
            text = await asyncio.to_thread(extract_text_from_pdf, pdf_path)
            parsed = parse_answer_key_text(text)
            file_errors.extend(parsed.errors)

            extracted_answers = len(parsed.answers)
            max_qno = max(parsed.answers.keys()) if parsed.answers else 0

            match = match_exam_for_pdf(
                pdf_path.name,
                exams,
                extracted_max_qno=max_qno if max_qno > 0 else None,
                min_score=float(req.min_match_score),
            )

            if not match.exam:
                cand = ", ".join(
                    f"{c.exam.id}:{c.exam.exam_dir_name}({c.score:.2f})"
                    for c in match.candidates
                )
                if cand:
                    file_errors.append(f"Candidates: {cand}")
                file_errors.append(match.reason)

                results.append(
                    AnswerPdfImportFileResult(
                        pdf_filename=pdf_path.name,
                        match_score=match.score,
                        extracted_answers=extracted_answers,
                        max_question_no=max_qno,
                        imported=0,
                        skipped=extracted_answers,
                        errors=file_errors[:10],
                    )
                )
                skipped_total += extracted_answers
                continue

            if req.dry_run:
                results.append(
                    AnswerPdfImportFileResult(
                        pdf_filename=pdf_path.name,
                        matched_exam_id=match.exam.id,
                        matched_exam_dir_name=match.exam.exam_dir_name,
                        match_score=match.score,
                        extracted_answers=extracted_answers,
                        max_question_no=max_qno,
                        imported=0,
                        skipped=0,
                        errors=file_errors[:10],
                    )
                )
                continue

            async with db.transaction():
                question_rows = await db.fetch_all(
                    "SELECT question_no FROM exam_questions WHERE exam_id = ?",
                    (match.exam.id,),
                )
            valid_qnos = {int(r["question_no"]) for r in question_rows} if question_rows else None
            force_fold = False
            if valid_qnos:
                has_big = any(qno > 1000 for qno in valid_qnos)
                has_sub = any(111 <= qno <= 130 for qno in valid_qnos)
                force_fold = has_big and not has_sub

            folded_map, fold_errors = fold_data_analysis_answers_for_exam(
                parsed.answers,
                question_count=match.exam.question_count,
                force=force_fold,
            )
            file_errors.extend(fold_errors)

            if valid_qnos:
                folded_map = {int(qno): ans for qno, ans in folded_map.items() if int(qno) in valid_qnos}

            imported, skipped, upsert_errs = await _upsert_answers_for_exam(
                match.exam.id,
                folded_map,
                source=req.source,
                question_count=match.exam.question_count,
                errors=file_errors,
                valid_question_nos=valid_qnos,
                cleanup_data_analysis_sub_answers=force_fold,
            )
            imported_total += imported
            skipped_total += skipped

            results.append(
                AnswerPdfImportFileResult(
                    pdf_filename=pdf_path.name,
                    matched_exam_id=match.exam.id,
                    matched_exam_dir_name=match.exam.exam_dir_name,
                    match_score=match.score,
                    extracted_answers=extracted_answers,
                    max_question_no=max_qno,
                    imported=imported,
                    skipped=skipped,
                    errors=upsert_errs[:10],
                )
            )
        except Exception as e:
            results.append(
                AnswerPdfImportFileResult(
                    pdf_filename=pdf_path.name,
                    imported=0,
                    skipped=0,
                    errors=[str(e)],
                )
            )

    return AnswerPdfDirImportResult(
        files_total=len(pdf_files),
        imported_total=imported_total,
        skipped_total=skipped_total,
        results=results,
    )


@router.get("/exams/local/directories", response_model=LocalDirectoriesResponse)
async def list_local_exam_directories():
    """列出pdf_images目录下的所有试卷目录"""
    base_dir = LEGACY_PDF_IMAGES_DIR.resolve()

    if not base_dir.exists() or not base_dir.is_dir():
        return LocalDirectoriesResponse(directories=[])

    directories = []
    for item in sorted(base_dir.iterdir()):
        if item.is_dir():
            # 检查是否包含all_questions子目录
            all_questions_dir = item / "all_questions"
            if all_questions_dir.exists() and all_questions_dir.is_dir():
                directories.append(item.name)

    return LocalDirectoriesResponse(directories=directories)


@router.post("/exams/local:import", response_model=LocalExamImportResult)
async def import_local_exam(req: LocalExamImportRequest):
    """从本地目录导入试卷（跳过PDF处理流程）"""
    # 验证exam_dir_name不为空
    if not req.exam_dir_name or not req.exam_dir_name.strip():
        raise HTTPException(status_code=400, detail="exam_dir_name cannot be empty")

    # 禁止相对路径
    if req.exam_dir_name in (".", "..") or "/" in req.exam_dir_name or "\\" in req.exam_dir_name:
        raise HTTPException(status_code=400, detail="Invalid exam_dir_name")

    base_dir = LEGACY_PDF_IMAGES_DIR.resolve()
    target_dir = (base_dir / req.exam_dir_name).resolve()

    # 防止路径遍历攻击
    try:
        target_dir.relative_to(base_dir)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid directory (path traversal)")

    if not target_dir.exists() or not target_dir.is_dir():
        raise HTTPException(status_code=404, detail="Directory not found")

    # 扫描目录
    scan = await _scan_local_exam_directory(
        target_dir,
        display_name=req.display_name,
    )

    # 如果是dry_run，只返回扫描结果
    if req.dry_run:
        return LocalExamImportResult(
            exam_dir_name=scan["exam_dir_name"],
            display_name=scan.get("display_name"),
            question_count=int(scan.get("question_count", 0)),
            data_analysis_count=int(scan.get("data_analysis_count", 0)),
            imported=0,
            skipped=0,
            warnings=list(scan.get("warnings") or []),
            errors=list(scan.get("errors") or []),
        )

    # 执行导入
    return await _import_local_questions(scan, overwrite=req.overwrite)
