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


# ==================== API Endpoints ====================

@router.get("/exams", response_model=List[ExamOut])
async def list_exams():
    """获取所有试卷列表"""
    db = get_db_manager()
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
