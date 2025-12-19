#!/usr/bin/env python3
"""
数据回填脚本 - 从已处理的PDF生成 exams 和 exam_questions 数据

用途：
- 将现有已处理的PDF文件元数据导入到新的 exams 和 exam_questions 表中
- 支持幂等性（可重复运行）

使用方法：
  python scripts/backfill_exams.py
  python scripts/backfill_exams.py --dry-run  # 预览模式，不实际写入
"""

import asyncio
import sys
import argparse
from pathlib import Path
from typing import List, Dict, Any

# 添加项目根目录到 Python 路径
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from backend.src.common.types import LEGACY_PDF_IMAGES_DIR
from backend.src.db.connection import get_db_manager


async def backfill_exams(dry_run: bool = False):
    """回填 exams 和 exam_questions 数据"""

    # 初始化数据库
    db_path = PROJECT_ROOT / "data" / "tasks.db"
    db = get_db_manager(db_path)
    await db.init()

    print("=" * 60)
    print("数据回填脚本")
    print("=" * 60)

    if dry_run:
        print("\n[DRY RUN 模式] - 不会实际写入数据库")

    # 获取所有已完成的任务
    tasks = await db.fetch_all(
        """
        SELECT task_id, exam_dir_name, pdf_name, file_hash, finished_at
        FROM tasks
        WHERE status = 'completed' AND exam_dir_name IS NOT NULL AND deleted_at IS NULL
        ORDER BY finished_at DESC
        """
    )

    print(f"\n找到 {len(tasks)} 个已完成的任务\n")

    processed_count = 0
    skipped_count = 0
    error_count = 0

    for task in tasks:
        task_id = task["task_id"]
        exam_dir_name = task["exam_dir_name"]
        pdf_name = task["pdf_name"]
        file_hash = task["file_hash"]
        finished_at = task["finished_at"]

        print(f"处理: {exam_dir_name} (task_id={task_id[:8]}...)")

        # 检查目录是否存在
        exam_dir = LEGACY_PDF_IMAGES_DIR / exam_dir_name
        if not exam_dir.is_dir():
            print(f"  ⚠️  跳过: 目录不存在")
            skipped_count += 1
            continue

        all_questions_dir = exam_dir / "all_questions"
        if not all_questions_dir.is_dir():
            print(f"  ⚠️  跳过: all_questions 目录不存在")
            skipped_count += 1
            continue

        # 扫描题目文件
        question_files = sorted(all_questions_dir.glob("q*.png"))
        question_count = len(question_files)

        if question_count == 0:
            print(f"  ⚠️  跳过: 没有题目文件")
            skipped_count += 1
            continue

        if dry_run:
            print(f"  ✓  [DRY RUN] 将创建 exam: {pdf_name} ({question_count} 题)")
            processed_count += 1
            continue

        try:
            # 检查 exam 是否已存在
            existing_exam = await db.fetch_one(
                "SELECT id FROM exams WHERE exam_dir_name = ?",
                (exam_dir_name,)
            )

            if existing_exam:
                exam_id = existing_exam["id"]
                print(f"  ✓  Exam 已存在 (id={exam_id})")
            else:
                # 插入 exam 记录
                await db.execute(
                    """
                    INSERT INTO exams (task_id, exam_dir_name, display_name, file_hash, question_count, processed_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (task_id, exam_dir_name, pdf_name, file_hash, question_count, finished_at)
                )

                # 获取刚插入的 exam_id
                exam_row = await db.fetch_one(
                    "SELECT id FROM exams WHERE exam_dir_name = ?",
                    (exam_dir_name,)
                )
                exam_id = exam_row["id"]
                print(f"  ✓  创建 Exam (id={exam_id})")

            # 插入题目记录
            questions_inserted = 0
            for q_file in question_files:
                # 从文件名提取题号（如 q1.png -> 1）
                try:
                    question_no = int(q_file.stem[1:])  # 去掉 'q' 前缀
                except ValueError:
                    continue

                # 检查题目是否已存在
                existing_question = await db.fetch_one(
                    "SELECT id FROM exam_questions WHERE exam_id = ? AND question_no = ?",
                    (exam_id, question_no)
                )

                if not existing_question:
                    await db.execute(
                        """
                        INSERT INTO exam_questions (exam_id, question_no, image_filename)
                        VALUES (?, ?, ?)
                        """,
                        (exam_id, question_no, q_file.name)
                    )
                    questions_inserted += 1

            if questions_inserted > 0:
                print(f"  ✓  插入 {questions_inserted} 个题目")
            else:
                print(f"  ✓  所有题目已存在")

            # 提交事务
            await db.commit()
            processed_count += 1

        except Exception as e:
            print(f"  ❌ 错误: {e}")
            error_count += 1

    # 汇总
    print("\n" + "=" * 60)
    print("回填完成！")
    print("=" * 60)
    print(f"已处理: {processed_count}")
    print(f"跳过:   {skipped_count}")
    print(f"错误:   {error_count}")
    print(f"总计:   {len(tasks)}")


def main():
    parser = argparse.ArgumentParser(description="回填 exams 数据")
    parser.add_argument("--dry-run", action="store_true", help="预览模式，不实际写入")
    args = parser.parse_args()

    try:
        asyncio.run(backfill_exams(dry_run=args.dry_run))
    except KeyboardInterrupt:
        print("\n\n操作已取消")
        return 1
    except Exception as e:
        print(f"\n\n❌ 发生错误: {e}")
        import traceback
        traceback.print_exc()
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
