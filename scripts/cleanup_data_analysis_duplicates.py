"""
清理已处理试卷中的资料分析子题重复文件

资料分析子题 (q111-q130) 已被合并到 data_analysis_*.png 中，
不应该单独存在于 all_questions 文件夹中。

此脚本用于：
1. 检测并删除现有试卷中的 q111-q130.png 文件
2. 同时清理数据库中对应的记录

用法:
    python scripts/cleanup_data_analysis_duplicates.py [--dry-run] [--db]

参数:
    --dry-run   仅显示要删除的文件，不实际删除
    --db        同时清理数据库中的记录
"""

import re
import sqlite3
import sys
from pathlib import Path

# 资料分析题号范围
DA_QNO_START = 111
DA_QNO_END = 130

# 项目路径
PROJECT_ROOT = Path(__file__).parent.parent
PDF_IMAGES_DIR = PROJECT_ROOT / "pdf_images"
DB_PATH = PROJECT_ROOT / "data" / "tasks.db"


def is_data_analysis_qno(qno: int) -> bool:
    """判断题号是否属于资料分析范围"""
    return DA_QNO_START <= qno <= DA_QNO_END


def cleanup_files(dry_run: bool = True) -> tuple[int, int]:
    """
    清理所有试卷中的资料分析子题文件

    Returns:
        (exam_count, file_count): 处理的试卷数和删除的文件数
    """
    if not PDF_IMAGES_DIR.exists():
        print(f"❌ pdf_images 目录不存在: {PDF_IMAGES_DIR}")
        return 0, 0

    exam_count = 0
    file_count = 0

    for exam_dir in sorted(PDF_IMAGES_DIR.iterdir()):
        if not exam_dir.is_dir():
            continue

        all_questions_dir = exam_dir / "all_questions"
        if not all_questions_dir.exists():
            continue

        exam_files_deleted = 0
        for png_file in sorted(all_questions_dir.glob("q*.png")):
            match = re.match(r"^q(\d+)\.png$", png_file.name, re.IGNORECASE)
            if not match:
                continue

            try:
                qno = int(match.group(1))
            except ValueError:
                continue

            if is_data_analysis_qno(qno):
                if dry_run:
                    print(f"  [DRY] 将删除: {png_file.relative_to(PROJECT_ROOT)}")
                else:
                    png_file.unlink()
                    print(f"  删除: {png_file.name}")
                exam_files_deleted += 1
                file_count += 1

        if exam_files_deleted > 0:
            prefix = "[DRY] " if dry_run else ""
            print(f"{prefix}{exam_dir.name}: 删除 {exam_files_deleted} 个文件")
            exam_count += 1

    return exam_count, file_count


def cleanup_database(dry_run: bool = True) -> int:
    """
    清理数据库中的资料分析子题记录

    Returns:
        删除的记录数
    """
    if not DB_PATH.exists():
        print(f"⚠️  数据库不存在: {DB_PATH}")
        return 0

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    try:
        # 查询要删除的记录数
        cursor.execute(
            """
            SELECT COUNT(*) as cnt FROM exam_questions
            WHERE question_no BETWEEN ? AND ?
            """,
            (DA_QNO_START, DA_QNO_END),
        )
        count = cursor.fetchone()["cnt"]

        if count == 0:
            print("数据库中没有资料分析子题记录")
            return 0

        if dry_run:
            print(f"[DRY] 将从数据库删除 {count} 条资料分析子题记录")
            # 显示详细信息
            cursor.execute(
                """
                SELECT e.exam_dir_name, eq.question_no
                FROM exam_questions eq
                JOIN exams e ON eq.exam_id = e.id
                WHERE eq.question_no BETWEEN ? AND ?
                ORDER BY e.exam_dir_name, eq.question_no
                """,
                (DA_QNO_START, DA_QNO_END),
            )
            for row in cursor.fetchall():
                print(f"  [DRY] {row['exam_dir_name']}: q{row['question_no']}")
        else:
            cursor.execute(
                """
                DELETE FROM exam_questions
                WHERE question_no BETWEEN ? AND ?
                """,
                (DA_QNO_START, DA_QNO_END),
            )
            conn.commit()
            print(f"已从数据库删除 {count} 条资料分析子题记录")

        return count

    finally:
        conn.close()


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="清理资料分析子题重复文件和数据库记录"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="仅显示要删除的内容，不实际执行删除",
    )
    parser.add_argument(
        "--db",
        action="store_true",
        help="同时清理数据库中的记录",
    )
    args = parser.parse_args()

    print("=" * 60)
    print("  清理资料分析子题重复文件")
    print("=" * 60)
    print(f"  资料分析题号范围: {DA_QNO_START} - {DA_QNO_END}")
    print(f"  pdf_images 目录: {PDF_IMAGES_DIR}")
    if args.dry_run:
        print("  模式: DRY RUN (仅预览)")
    else:
        print("  模式: 实际删除")
    print("=" * 60)
    print()

    # 清理文件
    print("▶ 清理文件...")
    exam_count, file_count = cleanup_files(dry_run=args.dry_run)
    print()

    # 清理数据库
    if args.db:
        print("▶ 清理数据库...")
        db_count = cleanup_database(dry_run=args.dry_run)
        print()
    else:
        db_count = 0

    # 汇总
    print("=" * 60)
    if args.dry_run:
        print("预览完成 (DRY RUN)")
        print(f"  将处理 {exam_count} 个试卷")
        print(f"  将删除 {file_count} 个文件")
        if args.db:
            print(f"  将删除 {db_count} 条数据库记录")
        print()
        print("若要实际执行，请去掉 --dry-run 参数")
    else:
        print("清理完成!")
        print(f"  处理了 {exam_count} 个试卷")
        print(f"  删除了 {file_count} 个文件")
        if args.db:
            print(f"  删除了 {db_count} 条数据库记录")
    print("=" * 60)

    return 0


if __name__ == "__main__":
    sys.exit(main())
