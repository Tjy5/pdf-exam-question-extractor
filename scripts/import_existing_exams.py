#!/usr/bin/env python3
"""
将已处理的试卷文件夹导入到数据库

用法:
    python scripts/import_existing_exams.py
"""

import sys
import sqlite3
from pathlib import Path
from datetime import datetime

PROJECT_ROOT = Path(__file__).parent.parent
PDF_IMAGES_DIR = PROJECT_ROOT / "pdf_images"
DB_PATH = PROJECT_ROOT / "data" / "tasks.db"


def now_iso8601() -> str:
    return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def import_exam(conn: sqlite3.Connection, exam_dir: Path) -> int:
    """导入单个试卷"""
    cursor = conn.cursor()

    exam_dir_name = exam_dir.name
    all_questions_dir = exam_dir / "all_questions"

    if not all_questions_dir.exists():
        print(f"  ⚠️  跳过 {exam_dir_name}: 缺少 all_questions 目录")
        return 0

    # 统计题目数量
    question_files = sorted(all_questions_dir.glob("q*.png"))
    question_count = len(question_files)

    if question_count == 0:
        print(f"  ⚠️  跳过 {exam_dir_name}: 没有题目文件")
        return 0

    print(f"  📝 {exam_dir_name}")
    print(f"     题目数: {question_count}")

    # 检查是否已存在
    existing = cursor.execute(
        "SELECT id FROM exams WHERE exam_dir_name = ?",
        (exam_dir_name,)
    ).fetchone()

    if existing:
        exam_id = existing[0]
        print(f"     已存在 (ID={exam_id}), 更新题目数...")
        cursor.execute(
            "UPDATE exams SET question_count = ?, updated_at = ? WHERE id = ?",
            (question_count, now_iso8601(), exam_id)
        )
    else:
        # 创建试卷记录
        now = now_iso8601()
        cursor.execute(
            """
            INSERT INTO exams (exam_dir_name, question_count, created_at, updated_at)
            VALUES (?, ?, ?, ?)
            """,
            (exam_dir_name, question_count, now, now)
        )
        exam_id = cursor.lastrowid
        print(f"     ✅ 创建成功 (ID={exam_id})")

    # 创建题目记录
    created_questions = 0
    for qfile in question_files:
        # 从文件名提取题号 (q1.png -> 1)
        question_no = int(qfile.stem[1:])
        image_filename = qfile.name

        # 检查是否已存在
        exists = cursor.execute(
            "SELECT id FROM exam_questions WHERE exam_id = ? AND question_no = ?",
            (exam_id, question_no)
        ).fetchone()

        if not exists:
            cursor.execute(
                """
                INSERT INTO exam_questions (exam_id, question_no, image_filename, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (exam_id, question_no, image_filename, now_iso8601())
            )
            created_questions += 1

    if created_questions > 0:
        print(f"     ✅ 创建了 {created_questions} 条题目记录")

    return 1


def main():
    print("=" * 60)
    print("  导入已处理的试卷到数据库")
    print("=" * 60)

    if not PDF_IMAGES_DIR.exists():
        print(f"❌ 错误: {PDF_IMAGES_DIR} 不存在")
        return 1

    if not DB_PATH.exists():
        print(f"❌ 错误: {DB_PATH} 不存在")
        return 1

    # 查找所有试卷文件夹
    exam_dirs = [d for d in PDF_IMAGES_DIR.iterdir() if d.is_dir()]

    if not exam_dirs:
        print(f"❌ 在 {PDF_IMAGES_DIR} 中没有找到试卷文件夹")
        return 1

    print(f"\n找到 {len(exam_dirs)} 个试卷文件夹\n")

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    try:
        imported = 0
        for exam_dir in exam_dirs:
            imported += import_exam(conn, exam_dir)

        conn.commit()

        print("\n" + "=" * 60)
        print(f"✅ 成功导入 {imported} 个试卷")
        print("=" * 60)

        # 显示数据库中的试卷列表
        cursor = conn.cursor()
        exams = cursor.execute(
            "SELECT id, exam_dir_name, question_count FROM exams ORDER BY id"
        ).fetchall()

        print("\n当前数据库中的试卷:")
        for exam in exams:
            print(f"  ID={exam[0]}: {exam[1]} ({exam[2]} 题)")

    except Exception as e:
        conn.rollback()
        print(f"\n❌ 错误: {e}")
        return 1
    finally:
        conn.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())
