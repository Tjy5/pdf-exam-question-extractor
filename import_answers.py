#!/usr/bin/env python3
"""批量导入答案脚本"""

import asyncio
import io
import re
import sys
import sqlite3
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

# Fix Windows console encoding (avoid UnicodeEncodeError on emoji/symbols)
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")

from backend.src.services.answers.answer_pdf_importer import (
    DATA_ANALYSIS_GROUP_SIZE,
    ExamInfo,
    extract_text_from_pdf,
    fold_data_analysis_answers_for_exam,
    is_data_analysis_big_qno,
    parse_answer_key_text,
    match_exam_for_pdf,
)

DB_PATH = PROJECT_ROOT / "data" / "tasks.db"
ANSWER_DIR = PROJECT_ROOT / "answer"


async def import_answers():
    """导入答案"""
    print("=" * 60)
    print("批量导入PDF答案")
    print("=" * 60)

    if not ANSWER_DIR.exists():
        print(f"[ERROR] 答案目录不存在: {ANSWER_DIR}")
        return 1

    if not DB_PATH.exists():
        print(f"[ERROR] 数据库不存在: {DB_PATH}")
        return 1

    # 获取所有PDF文件
    pdf_files = sorted([p for p in ANSWER_DIR.iterdir() if p.is_file() and p.suffix.lower() == ".pdf"])
    print(f"\n找到 {len(pdf_files)} 个PDF文件\n")

    # 连接数据库
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    try:
        # 获取所有试卷
        cursor = conn.cursor()
        exam_rows = cursor.execute(
            "SELECT id, exam_dir_name, display_name, question_count FROM exams ORDER BY id"
        ).fetchall()

        exams = [
            ExamInfo(
                id=int(r["id"]),
                exam_dir_name=str(r["exam_dir_name"] or ""),
                display_name=str(r["display_name"]) if r["display_name"] is not None else None,
                question_count=int(r["question_count"] or 0),
            )
            for r in exam_rows
        ]

        print(f"数据库中有 {len(exams)} 个试卷\n")

        imported_total = 0

        # 处理每个PDF
        for pdf_path in pdf_files:
            print(f"处理: {pdf_path.name}")

            try:
                # 提取文本
                text = await asyncio.to_thread(extract_text_from_pdf, pdf_path)

                # 解析答案
                parsed = parse_answer_key_text(text)
                extracted = len(parsed.answers)
                max_qno = max(parsed.answers.keys()) if parsed.answers else 0

                print(f"  解析到 {extracted} 个答案 (题号 1-{max_qno})")

                if parsed.errors:
                    print(f"  [WARN] {len(parsed.errors)} 个解析错误")

                # 匹配试卷
                match = match_exam_for_pdf(
                    pdf_path.name,
                    exams,
                    extracted_max_qno=max_qno if max_qno > 0 else None,
                    min_score=0.55,  # 降低阈值以匹配名称差异较大的试卷
                )

                if not match.exam:
                    print(f"  [WARN] 无法匹配试卷 (score={match.score:.2f}): {match.reason}")
                    if match.candidates:
                        print("     候选:")
                        for c in match.candidates[:3]:
                            print(f"       - {c.exam.exam_dir_name} (score={c.score:.2f})")
                    continue

                print(f"  [OK] 匹配到: {match.exam.exam_dir_name} (score={match.score:.2f})")

                # Determine schema from existing questions (more reliable than question_count).
                qrows = cursor.execute(
                    "SELECT question_no FROM exam_questions WHERE exam_id = ?",
                    (match.exam.id,),
                ).fetchall()
                valid_qnos = {int(r["question_no"]) for r in qrows} if qrows else None
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
                if fold_errors:
                    print(f"  [WARN] 资料分析折叠警告: {len(fold_errors)} 个")

                if valid_qnos:
                    folded_map = {int(qno): ans for qno, ans in folded_map.items() if int(qno) in valid_qnos}

                # Clean up legacy sub-question answers (Q111-130) when using big-question schema.
                if force_fold:
                    cursor.execute(
                        "DELETE FROM exam_answers WHERE exam_id = ? AND question_no BETWEEN 111 AND 130",
                        (match.exam.id,),
                    )

                # 导入答案
                imported = 0
                allowed = {"A", "B", "C", "D", "E"}
                for qno in sorted(folded_map.keys()):
                    raw = str(folded_map[qno] or "").strip().upper()
                    if qno <= 0 or not raw:
                        continue

                    if is_data_analysis_big_qno(qno):
                        letters = re.findall(r"[A-E]", raw)
                        if len(letters) != int(DATA_ANALYSIS_GROUP_SIZE):
                            continue
                        ans = "".join(letters)
                    else:
                        if len(raw) != 1 or raw not in allowed:
                            continue
                        if valid_qnos is None and match.exam.question_count and qno > match.exam.question_count:
                            continue
                        ans = raw

                    cursor.execute(
                        """
                        INSERT INTO exam_answers (exam_id, question_no, answer, source)
                        VALUES (?, ?, ?, ?)
                        ON CONFLICT(exam_id, question_no) DO UPDATE SET
                            answer = excluded.answer,
                            source = excluded.source,
                            updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                        """,
                        (match.exam.id, int(qno), ans, "pdf_import"),
                    )
                    imported += 1

                if imported > 0:
                    cursor.execute(
                        "UPDATE exams SET has_answers = 1, updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = ?",
                        (match.exam.id,),
                    )

                imported_total += imported
                print(f"  导入了 {imported} 个答案")

            except Exception as e:
                print(f"  [ERROR] {e}")
                continue

        conn.commit()

        print("\n" + "=" * 60)
        print(f"[OK] 完成! 共导入 {imported_total} 个答案")
        print("=" * 60)

        return 0

    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(import_answers()))
