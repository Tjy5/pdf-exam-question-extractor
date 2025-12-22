"""
Users Router - 用户错题标记和管理
"""

from typing import Dict, Any, List
from pydantic import BaseModel

from fastapi import APIRouter, HTTPException
from ...db.connection import get_db_manager

router = APIRouter(prefix="/api/users", tags=["users"])


# ==================== Request/Response Models ====================

class MarkWrongRequest(BaseModel):
    """错题标记请求"""
    answers: Dict[str, str]  # question_no -> user_answer


class WrongQuestionOut(BaseModel):
    """错题输出"""
    question_no: int
    user_answer: str
    correct_answer: str
    status: str = "wrong"
    marked_at: str


class MarkWrongResult(BaseModel):
    """错题标记结果"""
    wrong_questions: List[int]
    correct_questions: List[int]
    total: int


# ==================== Utility Functions ====================

def _normalize_answer(answer: str) -> str:
    """答案归一化（简单版：大写+排序）"""
    if not answer:
        return ""

    # 提取所有字母并排序
    letters = [c.upper() for c in answer if c.isalpha()]
    return "".join(sorted(set(letters)))


async def _ensure_user(user_id: str) -> int:
    """确保用户存在，返回数据库 ID"""
    db = get_db_manager()

    # 使用 UPSERT 避免并发下 "先查再插" 的竞态条件
    await db.execute(
        """
        INSERT INTO users (user_id, display_name, last_active_at)
        VALUES (?, ?, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
        ON CONFLICT(user_id) DO UPDATE SET
            last_active_at = excluded.last_active_at
        """,
        (user_id, f"用户_{user_id[:8]}")
    )

    user = await db.fetch_one("SELECT id FROM users WHERE user_id = ?", (user_id,))
    if not user:
        raise RuntimeError("Failed to ensure user")
    return int(user["id"])


# ==================== API Endpoints ====================

@router.post("/{user_id}/exams/{exam_id}/wrong-questions", response_model=MarkWrongResult)
async def mark_wrong_questions(user_id: str, exam_id: int, request: MarkWrongRequest):
    """
    批量标记错题

    对比用户答案与标准答案，自动标记错题
    """
    db = get_db_manager()

    wrong_list: List[int] = []
    correct_list: List[int] = []

    async with db.transaction():
        # 确保用户存在（写操作必须在事务中，避免跨请求提交/回滚问题）
        await _ensure_user(user_id)

        # 验证试卷存在
        exam = await db.fetch_one("SELECT id FROM exams WHERE id = ?", (exam_id,))
        if not exam:
            raise HTTPException(status_code=404, detail="Exam not found")
        for question_no_str, user_answer in request.answers.items():
            try:
                question_no = int(question_no_str)

                # 获取标准答案
                standard_answer_row = await db.fetch_one(
                    "SELECT answer FROM exam_answers WHERE exam_id = ? AND question_no = ?",
                    (exam_id, question_no)
                )

                if not standard_answer_row:
                    continue  # 没有标准答案，跳过

                standard_answer = str(standard_answer_row["answer"])

                # 归一化对比
                user_norm = _normalize_answer(user_answer)
                standard_norm = _normalize_answer(standard_answer)

                is_wrong = (user_norm != standard_norm)

                if is_wrong:
                    wrong_list.append(question_no)
                    status = "wrong"
                else:
                    correct_list.append(question_no)
                    status = "correct"

                # 插入或更新错题记录
                await db.execute(
                    """
                    INSERT INTO user_wrong_questions (user_id, exam_id, question_no, user_answer, status)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(user_id, exam_id, question_no) DO UPDATE SET
                        user_answer = excluded.user_answer,
                        status = excluded.status,
                        marked_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                    """,
                    (user_id, exam_id, question_no, user_answer, status)
                )

            except (ValueError, KeyError):
                continue

    return MarkWrongResult(
        wrong_questions=wrong_list,
        correct_questions=correct_list,
        total=len(wrong_list) + len(correct_list)
    )


@router.get("/{user_id}/exams/{exam_id}/wrong-questions", response_model=List[WrongQuestionOut])
async def get_wrong_questions(user_id: str, exam_id: int):
    """获取用户在某试卷的所有错题"""
    db = get_db_manager()

    async with db.transaction():
        rows = await db.fetch_all(
            """
            SELECT uwq.question_no, uwq.user_answer, uwq.status, uwq.marked_at,
                   ea.answer as correct_answer
            FROM user_wrong_questions uwq
            LEFT JOIN exam_answers ea ON uwq.exam_id = ea.exam_id AND uwq.question_no = ea.question_no
            WHERE uwq.user_id = ? AND uwq.exam_id = ? AND uwq.status = 'wrong'
            ORDER BY uwq.question_no
            """,
            (user_id, exam_id)
        )

    return [
        WrongQuestionOut(
            question_no=row["question_no"],
            user_answer=row["user_answer"] or "",
            correct_answer=row["correct_answer"] or "",
            status=row["status"],
            marked_at=row["marked_at"]
        )
        for row in rows
    ]
