"""
Migration tool: Import job_meta.json files to SQLite database.

Usage:
    python scripts/migrate_to_db.py [--data-dir PATH] [--db-path PATH] [--dry-run]

This script scans all exam directories for job_meta.json files and imports
them into the SQLite database for task history and persistence.
"""

import asyncio
import sys
import io
import json
import argparse
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, List

# Fix Windows console encoding
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.db import DatabaseManager, TaskRepository
from src.common.io import load_job_meta


def parse_iso_timestamp(ts_str: Optional[str]) -> Optional[str]:
    """Parse various timestamp formats to ISO8601."""
    if not ts_str:
        return None

    try:
        # Try parsing common formats
        for fmt in [
            "%Y-%m-%d %H:%M:%S.%f",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%dT%H:%M:%S.%fZ",
            "%Y-%m-%dT%H:%M:%SZ",
        ]:
            try:
                dt = datetime.strptime(ts_str, fmt)
                return dt.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
            except ValueError:
                continue

        # Fallback: return as-is if already in ISO format
        return ts_str
    except Exception:
        return None


async def migrate_exam_dir(
    exam_dir: Path,
    repo: TaskRepository,
    dry_run: bool = False
) -> tuple[bool, Optional[str]]:
    """
    Migrate a single exam directory to database as a historical task.

    Args:
        exam_dir: Path to exam directory
        repo: TaskRepository instance
        dry_run: If True, only print what would be done

    Returns:
        (success, error_message)
    """
    try:
        # Extract basic information from directory structure
        exam_dir_name = exam_dir.name
        pdf_name = exam_dir_name  # Use directory name as PDF name

        # Try to infer more info from exam_questions.json if exists
        questions_file = exam_dir / "exam_questions.json"
        total_questions = 0
        if questions_file.exists():
            with open(questions_file, "r", encoding="utf-8") as f:
                questions_data = json.load(f)
                if isinstance(questions_data, list):
                    # Count questions from pages
                    for page in questions_data:
                        if isinstance(page, dict) and "questions" in page:
                            total_questions += len(page["questions"])

        # Generate task_id from directory name
        task_id = f"historical_{exam_dir_name}"

        # Check if task already exists
        existing = await repo.get_task(task_id)
        if existing:
            return False, f"Task already migrated (task_id={task_id})"

        if dry_run:
            print(f"    [DRY-RUN] Would create task: {task_id}")
            print(f"              PDF: {pdf_name}")
            print(f"              Questions: {total_questions if total_questions > 0 else 'unknown'}")
            print(f"              Status: completed (assumed)")
            return True, None

        # Create task as completed historical record
        await repo.create_task(
            task_id=task_id,
            mode="auto",  # Assume auto mode for historical tasks
            pdf_name=pdf_name,
            file_hash=None,  # Unknown for historical tasks
            exam_dir_name=exam_dir_name,
            expected_pages=None,
        )

        # Mark as completed since it's a historical task
        await repo.update_task_status(
            task_id,
            status="completed",
            current_step=4,  # Assume all steps completed
        )

        # Add log about migration
        log_msg = f"✅ 历史任务导入（{total_questions}题）" if total_questions > 0 else "✅ 历史任务导入"
        await repo.add_log(
            task_id,
            log_msg,
            "success"
        )

        return True, None

    except Exception as e:
        return False, str(e)


async def main():
    """Main migration function."""
    parser = argparse.ArgumentParser(
        description="Migrate job_meta.json files to SQLite database"
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=PROJECT_ROOT / "pdf_images",
        help="Directory containing exam folders (default: pdf_images/)"
    )
    parser.add_argument(
        "--db-path",
        type=Path,
        default=PROJECT_ROOT / "data" / "tasks.db",
        help="SQLite database path (default: data/tasks.db)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be migrated without actually migrating"
    )

    args = parser.parse_args()

    print("=" * 70)
    print("Job Meta → SQLite Migration Tool")
    print("=" * 70)
    print(f"Data directory: {args.data_dir}")
    print(f"Database path:  {args.db_path}")
    print(f"Mode:           {'DRY RUN (no changes)' if args.dry_run else 'LIVE MIGRATION'}")
    print("=" * 70)

    if not args.data_dir.exists():
        print(f"\n❌ Error: Data directory not found: {args.data_dir}")
        return 1

    # Find all exam directories with exam_questions.json or job_meta.json
    print("\n[1/3] Scanning for exam directories...")
    exam_dirs = []
    for item in args.data_dir.iterdir():
        if item.is_dir():
            if (item / "exam_questions.json").exists() or (item / "job_meta.json").exists():
                exam_dirs.append(item)

    if not exam_dirs:
        print(f"No exam directories with job_meta.json found in {args.data_dir}")
        return 0

    print(f"Found {len(exam_dirs)} exam directory(ies) to migrate")

    # Initialize database
    print("\n[2/3] Initializing database...")
    db = DatabaseManager(args.db_path)
    await db.init()
    repo = TaskRepository(db)
    print(f"✓ Database ready: {args.db_path}")

    # Migrate each exam directory
    print(f"\n[3/3] Migrating exam directories...")
    print("-" * 70)

    success_count = 0
    skip_count = 0
    error_count = 0

    for i, exam_dir in enumerate(exam_dirs, 1):
        print(f"[{i}/{len(exam_dirs)}] {exam_dir.name}")

        success, error = await migrate_exam_dir(exam_dir, repo, dry_run=args.dry_run)

        if success:
            success_count += 1
            print(f"    ✓ Migrated successfully")
        elif error and "already migrated" in error:
            skip_count += 1
            print(f"    ⊘ Skipped: {error}")
        else:
            error_count += 1
            print(f"    ✗ Failed: {error}")

    # Summary
    print("-" * 70)
    print("\n" + "=" * 70)
    print("Migration Summary")
    print("=" * 70)
    print(f"Total directories:   {len(exam_dirs)}")
    print(f"✓ Migrated:         {success_count}")
    print(f"⊘ Skipped:          {skip_count}")
    print(f"✗ Failed:           {error_count}")
    print("=" * 70)

    if args.dry_run:
        print("\n💡 This was a dry run. No changes were made.")
        print("   Run without --dry-run to perform actual migration.")
    else:
        print(f"\n✅ Migration complete! Database: {args.db_path}")

    await db.close()
    return 0 if error_count == 0 else 1


if __name__ == "__main__":
    try:
        exit_code = asyncio.run(main())
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print("\n\n⚠️  Migration cancelled by user")
        sys.exit(130)
    except Exception as e:
        print(f"\n❌ Migration failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
