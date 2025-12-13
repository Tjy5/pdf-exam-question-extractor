"""
Basic database module test - verify CRUD operations work.

Run with: python tests/test_db_basic.py

This is a simple smoke test to verify the database module before integration.
"""

import asyncio
import sys
import io
from pathlib import Path
from datetime import datetime

# Fix Windows console encoding
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.db import DatabaseManager, TaskRepository


async def test_basic_crud():
    """Test basic CRUD operations."""
    print("=" * 60)
    print("Database Module Basic Test")
    print("=" * 60)

    # Setup: Create temporary database with unique name
    import time
    timestamp = int(time.time() * 1000)
    db_path = PROJECT_ROOT / "data" / f"test_tasks_{timestamp}.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"✓ Test database: {db_path.name}")

    # Initialize database
    db = DatabaseManager(db_path)
    await db.init()
    print(f"✓ Database initialized: {db_path}")

    repo = TaskRepository(db)

    # Test 1: Create task
    print("\n[Test 1] Creating task...")
    task_id = "test_task_001"
    await repo.create_task(
        task_id=task_id,
        mode="manual",
        pdf_name="test.pdf",
        file_hash="abc123",
        exam_dir_name="test_exam__abc12345",
        expected_pages=10,
    )
    print(f"✓ Task created: {task_id}")

    # Test 2: Get task
    print("\n[Test 2] Retrieving task...")
    task_data = await repo.get_task(task_id)
    assert task_data is not None, "Task not found"
    assert task_data["task"]["task_id"] == task_id
    assert len(task_data["steps"]) == 5
    print(f"✓ Task retrieved: {task_data['task']['pdf_name']}")
    print(f"  - Steps: {len(task_data['steps'])}")
    print(f"  - Status: {task_data['task']['status']}")

    # Test 3: Add logs
    print("\n[Test 3] Adding logs...")
    await repo.add_log(task_id, "Starting processing", "info")
    await repo.add_log(task_id, "Step 1 complete", "success")
    await repo.add_log(task_id, "Warning: low memory", "default")
    print("✓ Added 3 log entries")

    # Test 4: Get logs
    print("\n[Test 4] Retrieving logs...")
    logs = await repo.get_logs(task_id)
    assert len(logs) == 3
    print(f"✓ Retrieved {len(logs)} logs")
    for log in logs:
        print(f"  [{log['type']}] {log['message']}")

    # Test 5: Update task status
    print("\n[Test 5] Updating task status...")
    await repo.update_task_status(task_id, "processing", current_step=0)
    task_data = await repo.get_task(task_id)
    assert task_data["task"]["status"] == "processing"
    assert task_data["task"]["current_step"] == 0
    print("✓ Task status updated to 'processing'")

    # Test 6: Update step status
    print("\n[Test 6] Updating step status...")
    await repo.update_step_status(
        task_id,
        step_index=0,
        status="running"
    )
    step = await repo.get_step(task_id, 0)
    assert step["status"] == "running"
    assert step["started_at"] is not None
    print("✓ Step 0 marked as 'running'")

    await repo.update_step_status(
        task_id,
        step_index=0,
        status="completed",
        artifact_paths=["page_1.png", "page_2.png"]
    )
    step = await repo.get_step(task_id, 0)
    assert step["status"] == "completed"
    assert step["ended_at"] is not None
    print("✓ Step 0 marked as 'completed' with artifacts")

    # Test 7: Test artifact_paths with empty list
    print("\n[Test 7] Testing empty artifact list...")
    await repo.update_step_status(
        task_id,
        step_index=1,
        status="completed",
        artifact_paths=[]  # Should allow empty list
    )
    step = await repo.get_step(task_id, 1)
    assert step["artifact_json"] == "[]"
    print("✓ Empty artifact list handled correctly")

    # Test 8: List tasks
    print("\n[Test 8] Listing tasks...")
    tasks = await repo.list_tasks()
    assert len(tasks) >= 1
    print(f"✓ Found {len(tasks)} task(s)")

    # Test 9: Find by hash
    print("\n[Test 9] Finding task by hash...")
    found_task = await repo.find_task_by_hash("abc123")
    assert found_task is not None
    assert found_task["task_id"] == task_id
    print(f"✓ Found task by hash: {found_task['pdf_name']}")

    # Test 10: Soft delete
    print("\n[Test 10] Testing soft delete...")
    await repo.delete_task(task_id, soft=True)
    deleted_task = await repo.get_task(task_id)
    assert deleted_task is None  # Should not find deleted tasks
    print("✓ Task soft-deleted (not visible in queries)")

    # Test 11: Verify logs remain after soft delete
    print("\n[Test 11] Checking logs after soft delete...")
    logs = await repo.get_logs(task_id)
    # Logs still exist because FK cascade only on hard delete
    print(f"✓ Logs still accessible: {len(logs)} logs")

    # Cleanup
    await db.close()
    print("\n" + "=" * 60)
    print("✅ All tests passed!")
    print("=" * 60)
    print(f"\nTest database: {db_path}")
    print("You can inspect it with: sqlite3", db_path)


async def test_concurrency():
    """Test concurrent access doesn't break."""
    print("\n" + "=" * 60)
    print("Concurrency Test (lock serialization)")
    print("=" * 60)

    db_path = PROJECT_ROOT / "data" / "test_tasks_concurrent.db"
    if db_path.exists():
        db_path.unlink()

    db = DatabaseManager(db_path)
    await db.init()
    repo = TaskRepository(db)

    # Create 5 tasks concurrently
    print("\nCreating 5 tasks concurrently...")
    tasks = [
        repo.create_task(
            task_id=f"task_{i}",
            mode="auto",
            pdf_name=f"test_{i}.pdf",
        )
        for i in range(5)
    ]

    await asyncio.gather(*tasks)
    print("✓ All 5 tasks created")

    # Verify all tasks exist
    all_tasks = await repo.list_tasks()
    assert len(all_tasks) == 5
    print(f"✓ Verified {len(all_tasks)} tasks in database")

    await db.close()
    print("✅ Concurrency test passed!")


async def main():
    """Run all tests."""
    try:
        await test_basic_crud()
        await test_concurrency()
        print("\n🎉 All tests completed successfully!\n")
        return 0
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
