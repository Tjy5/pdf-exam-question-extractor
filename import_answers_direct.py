#!/usr/bin/env python3
"""直接测试答案导入（不通过HTTP）"""

import asyncio
import io
import re
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

# Fix Windows console encoding (avoid UnicodeEncodeError on emoji/symbols)
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")

from backend.src.services.answers.answer_pdf_importer import (
    DATA_ANALYSIS_GROUP_SIZE,
    extract_text_from_pdf,
    fold_data_analysis_answers_for_exam,
    is_data_analysis_big_qno,
    parse_answer_key_text,
)
from backend.src.db.connection import get_db_manager

DB_PATH = PROJECT_ROOT / "data" / "tasks.db"
ANSWER_DIR = PROJECT_ROOT / "answer"

# PDF与试卷ID的映射
MAPPINGS = {
    "【四海】25下半年一期行测套题冲刺1.pdf": 3,  # （1）【四海】25下半年1期套题班《行测》
    "【四海】25下半年一期行测套题冲刺2.pdf": 4,  # （2）【四海】25下半年1期套题班《行测》
    "【四海】25下半年一期行测套题冲刺3.pdf": 7,  # （3）【四海】25下半年1期套题班《行测》
    "【四海】25下半年一期行测套题冲刺4.pdf": 5,  # （4）【四海】25下半年1期套题班《行测》
    "【四海】25下半年一期行测套题冲刺5.pdf": 6,  # （5）【四海】25下半年1期套题班《行测》
}


async def import_answer_for_exam(pdf_path: Path, exam_id: int):
    """为指定试卷导入答案（直接访问数据库）"""
    print(f"\n处理: {pdf_path.name} → 试卷ID={exam_id}")

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
            for err in parsed.errors[:3]:
                print(f"       - {err}")

        # 获取数据库连接
        db = get_db_manager(DB_PATH)
        await db.init()

        # 验证试卷存在
        exam = await db.fetch_one(
            "SELECT id, question_count FROM exams WHERE id = ?",
            (exam_id,)
        )
        if not exam:
            print(f"  [ERROR] 试卷不存在: ID={exam_id}")
            return False

        question_count = int(exam["question_count"] or 0)
        print(f"  试卷有 {question_count} 道题")

        qrows = await db.fetch_all(
            "SELECT question_no FROM exam_questions WHERE exam_id = ?",
            (exam_id,),
        )
        valid_qnos = {int(r["question_no"]) for r in qrows} if qrows else None
        force_fold = False
        if valid_qnos:
            has_big = any(qno > 1000 for qno in valid_qnos)
            has_sub = any(111 <= qno <= 130 for qno in valid_qnos)
            force_fold = has_big and not has_sub

        folded_map, fold_errors = fold_data_analysis_answers_for_exam(
            parsed.answers,
            question_count=question_count,
            force=force_fold,
        )
        if fold_errors:
            print(f"  [WARN] 资料分析折叠警告: {len(fold_errors)} 个")
            for err in fold_errors[:3]:
                print(f"       - {err}")

        if valid_qnos:
            folded_map = {int(qno): ans for qno, ans in folded_map.items() if int(qno) in valid_qnos}

        # 导入答案
        imported = 0
        skipped = 0
        allowed = {"A", "B", "C", "D", "E"}

        async with db.transaction():
            if force_fold:
                await db.execute(
                    "DELETE FROM exam_answers WHERE exam_id = ? AND question_no BETWEEN 111 AND 130",
                    (exam_id,),
                )

            for qno in sorted(folded_map.keys()):
                raw = str(folded_map[qno] or "").strip().upper()
                if qno <= 0 or not raw:
                    skipped += 1
                    continue

                if is_data_analysis_big_qno(qno):
                    letters = re.findall(r"[A-E]", raw)
                    if len(letters) != int(DATA_ANALYSIS_GROUP_SIZE):
                        skipped += 1
                        continue
                    ans = "".join(letters)
                else:
                    if len(raw) != 1 or raw not in allowed:
                        skipped += 1
                        continue
                    if valid_qnos is None and question_count and qno > question_count:
                        skipped += 1
                        continue
                    ans = raw

                await db.execute(
                    """
                    INSERT INTO exam_answers (exam_id, question_no, answer, source)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(exam_id, question_no) DO UPDATE SET
                        answer = excluded.answer,
                        source = excluded.source,
                        updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                    """,
                    (exam_id, int(qno), ans, "pdf_manual"),
                )
                imported += 1

            if imported > 0:
                await db.execute(
                    "UPDATE exams SET has_answers = 1, updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = ?",
                    (exam_id,),
                )

        print(f"  [OK] 导入了 {imported} 个答案，跳过 {skipped} 个")
        return True

    except Exception as e:
        print(f"  [ERROR] {e}")
        import traceback
        traceback.print_exc()
        return False


async def main():
    print("=" * 60)
    print("手动指定试卷ID导入答案（直接访问数据库）")
    print("=" * 60)

    print("\n映射关系:")
    for pdf_name, exam_id in MAPPINGS.items():
        print(f"  {pdf_name} → 试卷{exam_id}")

    print("\n开始导入...")

    success_count = 0
    for pdf_filename, exam_id in MAPPINGS.items():
        pdf_path = ANSWER_DIR / pdf_filename
        if pdf_path.exists():
            if await import_answer_for_exam(pdf_path, exam_id):
                success_count += 1
        else:
            print(f"\n  [ERROR] 文件不存在: {pdf_filename}")

    print("\n" + "=" * 60)
    print(f"[OK] 完成! 成功导入 {success_count}/{len(MAPPINGS)} 个文件")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
