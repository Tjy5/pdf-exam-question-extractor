"""
同步 pdf_images 目录中的已处理试卷到数据库
"""
import asyncio
import json
import re
import sqlite3
from pathlib import Path
from datetime import datetime

PROJECT_ROOT = Path(__file__).parent.parent
PDF_IMAGES_DIR = PROJECT_ROOT / "pdf_images"
DB_PATH = PROJECT_ROOT / "data" / "tasks.db"


def now_iso8601() -> str:
    return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def sync_exams():
    """同步已处理试卷到数据库"""
    if not PDF_IMAGES_DIR.exists():
        print(f"pdf_images 目录不存在: {PDF_IMAGES_DIR}")
        return

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # 获取已存在的试卷
    cursor.execute("SELECT exam_dir_name FROM exams")
    existing = {row["exam_dir_name"] for row in cursor.fetchall()}

    imported_count = 0
    skipped_count = 0

    for exam_dir in sorted(PDF_IMAGES_DIR.iterdir()):
        if not exam_dir.is_dir():
            continue

        exam_dir_name = exam_dir.name
        all_questions_dir = exam_dir / "all_questions"

        # 跳过没有 all_questions 的目录
        if not all_questions_dir.exists():
            print(f"跳过 (无 all_questions): {exam_dir_name}")
            skipped_count += 1
            continue

        # 跳过已存在的
        if exam_dir_name in existing:
            print(f"跳过 (已存在): {exam_dir_name}")
            skipped_count += 1
            continue

        # 解析显示名称（去掉hash后缀）
        display_name = re.sub(r"__[a-f0-9]{8}$", "", exam_dir_name)

        # 统计题目数量
        question_files = list(all_questions_dir.glob("q*.png"))
        question_count = len(question_files)

        if question_count == 0:
            print(f"跳过 (无题目): {exam_dir_name}")
            skipped_count += 1
            continue

        now = now_iso8601()

        # 插入 exam 记录
        cursor.execute(
            """
            INSERT INTO exams (exam_dir_name, display_name, question_count, created_at, updated_at, processed_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (exam_dir_name, display_name, question_count, now, now, now),
        )
        exam_id = cursor.lastrowid

        # 插入 exam_questions 记录
        for qfile in question_files:
            # 从文件名提取题号: q1.png -> 1, q10.png -> 10
            match = re.match(r"q(\d+)\.png", qfile.name, re.IGNORECASE)
            if not match:
                continue
            qno = int(match.group(1))

            cursor.execute(
                """
                INSERT INTO exam_questions (exam_id, question_no, image_filename, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (exam_id, qno, qfile.name, now),
            )

        conn.commit()
        print(f"导入成功: {exam_dir_name} ({question_count} 题)")
        imported_count += 1

    conn.close()
    print(f"\n完成: 导入 {imported_count} 个试卷, 跳过 {skipped_count} 个")


if __name__ == "__main__":
    sync_exams()
