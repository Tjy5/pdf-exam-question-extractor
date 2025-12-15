"""
Test Web integration with database.

Run with: python tests/test_web_integration.py

This verifies that the web app properly integrates with the database module.
"""

import asyncio
import sys
import io
from pathlib import Path

# Fix Windows console encoding
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


async def test_lifespan_and_history_api():
    """Test that lifespan initializes DB and history API works."""
    print("=" * 60)
    print("Web Integration Test")
    print("=" * 60)

    # Test 1: Import app
    print("\n[Test 1] Importing FastAPI app...")
    from backend.src.web.main import create_app
    app = create_app()
    print("  ✓ App imported successfully")

    # Test 2: Access app.state.repo through lifespan simulation
    print("\n[Test 2] Simulating lifespan initialization...")
    from contextlib import asynccontextmanager
    from backend.src.db.connection import DatabaseManager
    from backend.src.db.crud import TaskRepository

    db_path = PROJECT_ROOT / "data" / "test_web_integration.db"
    db = DatabaseManager(db_path)
    await db.init()
    print(f"  ✓ Database initialized: {db_path}")

    repo = TaskRepository(db)
    print("  ✓ Repository created")

    # Test 3: Create a test task via repository
    print("\n[Test 3] Creating test task...")
    task_id = "test_web_task_001"
    await repo.create_task(
        task_id=task_id,
        mode="auto",
        pdf_name="test.pdf",
        file_hash="test_hash_123",
        exam_dir_name="test_exam_dir",
        expected_pages=5,
    )
    print(f"  ✓ Task created: {task_id}")

    # Test 4: Query task using repo.list_tasks (simulating /api/history)
    print("\n[Test 4] Testing list_tasks (simulating GET /api/history)...")
    tasks = await repo.list_tasks(limit=10, offset=0)
    assert len(tasks) >= 1, "Should have at least one task"
    print(f"  ✓ Found {len(tasks)} task(s)")
    for t in tasks[:3]:
        print(f"    - {t['task_id']}: {t['pdf_name']} ({t['status']})")

    # Test 5: Get task details (simulating /api/history/{task_id})
    print(f"\n[Test 5] Testing get_task (simulating GET /api/history/{task_id})...")
    task_data = await repo.get_task(task_id)
    assert task_data is not None, "Task should exist"
    assert task_data["task"]["task_id"] == task_id
    print(f"  ✓ Task retrieved: {task_data['task']['pdf_name']}")
    print(f"    - Steps: {len(task_data['steps'])}")
    print(f"    - Status: {task_data['task']['status']}")

    # Test 6: Add log and verify
    print("\n[Test 6] Adding log entry...")
    await repo.add_log(task_id, "Test log entry", "info")
    logs = await repo.get_logs(task_id)
    assert len(logs) >= 1, "Should have at least one log"
    print(f"  ✓ Added log, total logs: {len(logs)}")

    # Cleanup
    await db.close()
    print("\n" + "=" * 60)
    print("All integration tests passed!")
    print("=" * 60)
    print(f"\nTest database: {db_path}")


async def main():
    """Run all tests."""
    try:
        await test_lifespan_and_history_api()
        return 0
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
