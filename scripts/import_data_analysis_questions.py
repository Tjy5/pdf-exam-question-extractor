"""
导入资料分析大题到数据库

将已处理试卷中的 data_analysis_*.png 导入到 exam_questions 表中，
使用 question_no=1001-1004, question_type='data_analysis'

用法:
    python scripts/import_data_analysis_questions.py [--dry-run]
"""

import base64
import re
import sqlite3
import sys
from pathlib import Path

# 项目路径
PROJECT_ROOT = Path(__file__).parent.parent
PDF_IMAGES_DIR = PROJECT_ROOT / "pdf_images"
DB_PATH = PROJECT_ROOT / "data" / "tasks.db"


def import_data_analysis(dry_run: bool = False) -> tuple[int, int]:
    """
    导入所有试卷的资料分析大题到数据库

    Returns:
        (exam_count, question_count): 处理的试卷数和导入的题目数
    """
    if not PDF_IMAGES_DIR.exists():
        print(f"❌ pdf_images 目录不存在: {PDF_IMAGES_DIR}")
        return 0, 0

    if not DB_PATH.exists():
        print(f"❌ 数据库不存在: {DB_PATH}")
        return 0, 0

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    exam_count = 0
    question_count = 0

    try:
        # 获取所有已存在的试卷
        exams = cursor.execute(
            "SELECT id, exam_dir_name FROM exams"
        ).fetchall()

        for exam in exams:
            exam_id = exam["id"]
            exam_dir_name = exam["exam_dir_name"]
            exam_dir = PDF_IMAGES_DIR / exam_dir_name / "all_questions"

            if not exam_dir.exists():
                continue

            # 查找 data_analysis_*.png
            da_files = sorted(exam_dir.glob("data_analysis_*.png"))
            if not da_files:
                continue

            exam_imported = 0
            for da_file in da_files:
                m = re.match(r"^data_analysis_(\d+)\.png$", da_file.name, re.IGNORECASE)
                if not m:
                    continue

                da_order = int(m.group(1))
                if da_order <= 0:
                    continue

                # 使用 1000 + order 作为题号
                qno = 1000 + da_order

                # 检查是否已存在
                exists = cursor.execute(
                    "SELECT id FROM exam_questions WHERE exam_id = ? AND question_no = ?",
                    (exam_id, qno)
                ).fetchone()

                if exists:
                    if dry_run:
                        print(f"  [DRY] 已存在: {exam_dir_name} q{qno}")
                    continue

                if dry_run:
                    print(f"  [DRY] 将导入: {exam_dir_name} {da_file.name} -> q{qno}")
                    exam_imported += 1
                    question_count += 1
                    continue

                # 读取图片并转为 Base64
                try:
                    image_data = base64.b64encode(da_file.read_bytes()).decode("ascii")
                except Exception as e:
                    print(f"  ⚠️  读取失败: {da_file.name}: {e}")
                    continue

                # 插入数据库
                cursor.execute(
                    """
                    INSERT INTO exam_questions (
                        exam_id, question_no, question_type, image_filename, image_data, created_at
                    )
                    VALUES (?, ?, ?, ?, ?, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
                    """,
                    (exam_id, qno, "data_analysis", da_file.name, image_data),
                )
                exam_imported += 1
                question_count += 1

            if exam_imported > 0:
                prefix = "[DRY] " if dry_run else ""
                print(f"{prefix}{exam_dir_name}: 导入 {exam_imported} 个资料分析大题")
                exam_count += 1

        if not dry_run:
            conn.commit()

    finally:
        conn.close()

    return exam_count, question_count


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="导入资料分析大题到数据库"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="仅显示要导入的内容，不实际执行",
    )
    args = parser.parse_args()

    print("=" * 60)
    print("  导入资料分析大题到数据库")
    print("=" * 60)
    print(f"  pdf_images 目录: {PDF_IMAGES_DIR}")
    print(f"  数据库: {DB_PATH}")
    if args.dry_run:
        print("  模式: DRY RUN (仅预览)")
    else:
        print("  模式: 实际导入")
    print("=" * 60)
    print()

    exam_count, question_count = import_data_analysis(dry_run=args.dry_run)

    print()
    print("=" * 60)
    if args.dry_run:
        print("预览完成 (DRY RUN)")
        print(f"  将处理 {exam_count} 个试卷")
        print(f"  将导入 {question_count} 个资料分析大题")
        print()
        print("若要实际执行，请去掉 --dry-run 参数")
    else:
        print("导入完成!")
        print(f"  处理了 {exam_count} 个试卷")
        print(f"  导入了 {question_count} 个资料分析大题")
    print("=" * 60)

    return 0


if __name__ == "__main__":
    sys.exit(main())
