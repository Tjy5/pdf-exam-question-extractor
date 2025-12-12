#!/usr/bin/env python3
"""
migrate_data_v1_to_v2.py - 数据迁移脚本

将旧版本（v1）的数据结构迁移到新版本（v2）

旧结构:
    pdf_images/
    ├── 试卷名/
    │   ├── page_*.png
    │   ├── questions_page_*/
    │   └── exam_questions.json

新结构:
    data/output/
    ├── {exam_id}/
    │   ├── pages/                # 整页图片
    │   │   └── page_*.png
    │   ├── questions/            # 切好的题目
    │   │   ├── questions_page_*/
    │   │   └── all_questions/
    │   ├── metadata.json         # 试卷元数据
    │   └── exam_questions.json   # 题目汇总

使用方法:
    python scripts/migrate_data_v1_to_v2.py [--dry-run] [--keep-old]
"""

import argparse
import json
import shutil
import sys
from pathlib import Path
from datetime import datetime


def slugify(text: str) -> str:
    """
    将中文文件名转换为安全的英文slug

    示例:
        "2025年广东省公务员考试" -> "gd_2025"
        "1_四海_25下半年" -> "sihai_2025_h2"
    """
    # 简单映射规则
    mapping = {
        "广东": "gd",
        "四海": "sihai",
        "下半年": "h2",
        "上半年": "h1",
        "期": "",
        "套题班": "",
        "行测": "",
        "题": "",
        "年": "",
        "第一版": "v1",
    }

    slug = text
    for zh, en in mapping.items():
        slug = slug.replace(zh, en)

    # 移除特殊字符，只保留字母数字和下划线
    import re

    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[-\s]+", "_", slug).strip("_").lower()

    return slug


def create_metadata(exam_dir: Path, exam_name: str) -> dict:
    """创建试卷元数据"""
    # 统计信息
    page_images = list(exam_dir.glob("page_*.png"))
    question_dirs = list(exam_dir.glob("questions_page_*"))

    total_questions = 0
    for q_dir in question_dirs:
        if q_dir.is_dir():
            total_questions += len(list(q_dir.glob("q*.png")))

    metadata = {
        "exam_name": exam_name,
        "exam_id": slugify(exam_name),
        "migrated_from": str(exam_dir),
        "migration_date": datetime.now().isoformat(),
        "statistics": {
            "total_pages": len(page_images),
            "total_questions": total_questions,
            "question_dirs": len(question_dirs),
        },
        "source_version": "v1",
        "target_version": "v2",
    }

    return metadata


def migrate_exam_dir(
    old_dir: Path, new_base: Path, dry_run: bool = False) -> tuple[bool, str]:
    """
    迁移单个试卷目录

    Returns:
        (success, message)
    """
    exam_name = old_dir.name
    exam_id = slugify(exam_name)

    # 如果slug太短或为空，使用原名
    if len(exam_id) < 3:
        exam_id = exam_name.replace(" ", "_")

    new_dir = new_base / exam_id

    print(f"\n[*] 迁移: {exam_name}")
    print(f"   旧路径: {old_dir}")
    print(f"   新路径: {new_dir}")
    print(f"   ID: {exam_id}")

    if dry_run:
        print("   [模拟运行] 跳过实际操作")
        return True, "模拟运行成功"

    try:
        # 创建新目录结构
        pages_dir = new_dir / "pages"
        questions_dir = new_dir / "questions"
        pages_dir.mkdir(parents=True, exist_ok=True)
        questions_dir.mkdir(parents=True, exist_ok=True)

        # 1. 移动整页图片
        page_images = list(old_dir.glob("page_*.png"))
        print(f"   移动 {len(page_images)} 个页面图片...")
        for img in page_images:
            dest = pages_dir / img.name
            if not dest.exists():
                shutil.copy2(img, dest)

        # 2. 移动questions_page_*目录
        question_dirs = [d for d in old_dir.iterdir() if d.is_dir() and d.name.startswith("questions_page_")]
        print(f"   移动 {len(question_dirs)} 个题目目录...")
        for q_dir in question_dirs:
            dest = questions_dir / q_dir.name
            if dest.exists():
                shutil.rmtree(dest)
            shutil.copytree(q_dir, dest)

        # 3. 移动all_questions目录（如果存在）
        all_questions_old = old_dir / "all_questions"
        if all_questions_old.exists():
            all_questions_new = questions_dir / "all_questions"
            if all_questions_new.exists():
                shutil.rmtree(all_questions_new)
            shutil.copytree(all_questions_old, all_questions_new)
            print("   移动 all_questions 目录...")

        # 4. 复制exam_questions.json
        exam_json_old = old_dir / "exam_questions.json"
        if exam_json_old.exists():
            exam_json_new = new_dir / "exam_questions.json"
            shutil.copy2(exam_json_old, exam_json_new)
            print("   复制 exam_questions.json...")

        # 5. 创建metadata.json
        metadata = create_metadata(old_dir, exam_name)
        metadata_path = new_dir / "metadata.json"
        with metadata_path.open("w", encoding="utf-8") as f:
            json.dump(metadata, f, ensure_ascii=False, indent=2)
        print("   创建 metadata.json...")

        return True, f"成功迁移 {len(page_images)} 页，{len(question_dirs)} 个题目目录"

    except Exception as e:
        return False, f"迁移失败: {e}"


def main():
    parser = argparse.ArgumentParser(
        description="数据迁移脚本 v1 -> v2",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="模拟运行，不执行实际操作",
    )
    parser.add_argument(
        "--keep-old",
        action="store_true",
        help="保留旧数据（默认会保留）",
    )
    parser.add_argument(
        "--source",
        default="pdf_images",
        help="旧数据目录路径（默认: pdf_images）",
    )
    parser.add_argument(
        "--target",
        default="data/output",
        help="新数据目录路径（默认: data/output）",
    )

    args = parser.parse_args()

    old_base = Path(args.source)
    new_base = Path(args.target)

    print("=" * 60)
    print("数据迁移工具 v1 -> v2")
    print("=" * 60)

    if not old_base.exists():
        print(f"\n[ERROR] 源目录不存在: {old_base}")
        sys.exit(1)

    # 扫描所有子目录
    exam_dirs = [d for d in old_base.iterdir() if d.is_dir() and not d.name.startswith(".")]

    if not exam_dirs:
        print(f"\n[WARNING] 在 {old_base} 中没有找到试卷目录")
        sys.exit(0)

    print(f"\n找到 {len(exam_dirs)} 个试卷目录:")
    for d in exam_dirs:
        print(f"  - {d.name}")

    if args.dry_run:
        print("\n[DRY-RUN] 模拟运行模式（不会实际修改文件）")
    else:
        print(f"\n[WARNING] 即将开始迁移数据到: {new_base}")
        response = input("确认继续? [y/N]: ")
        if response.lower() != "y":
            print("已取消")
            sys.exit(0)

    # 创建目标目录
    new_base.mkdir(parents=True, exist_ok=True)

    # 迁移每个试卷
    success_count = 0
    fail_count = 0

    for exam_dir in exam_dirs:
        success, message = migrate_exam_dir(exam_dir, new_base, dry_run=args.dry_run)
        if success:
            print(f"   [OK] {message}")
            success_count += 1
        else:
            print(f"   [FAIL] {message}")
            fail_count += 1

    # 汇总报告
    print("\n" + "=" * 60)
    print("迁移完成!")
    print("=" * 60)
    print(f"  成功: {success_count}")
    print(f"  失败: {fail_count}")

    if not args.dry_run:
        print(f"\n新数据位置: {new_base}")
        if args.keep_old:
            print(f"旧数据保留在: {old_base}")
            print("[WARNING] 建议验证数据无误后手动删除旧数据")
        print("\n[TODO] 下一步:")
        print("  1. 验证新数据结构是否正确")
        print("  2. 运行测试: python manage.py cli")
        print("  3. 确认无误后可删除旧数据")


if __name__ == "__main__":
    main()
