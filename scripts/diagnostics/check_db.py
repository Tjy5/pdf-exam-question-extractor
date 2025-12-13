import asyncio
import sys
from pathlib import Path
sys.path.insert(0, '.')
from src.db import DatabaseManager, TaskRepository

async def check():
    db = DatabaseManager(Path('data/tasks.db'))
    await db.init()
    repo = TaskRepository(db)

    tasks = await repo.list_tasks(limit=100)
    print(f'总任务数: {len(tasks)}')
    print('\n前5个任务:')
    for t in tasks[:5]:
        print(f"  - {t['task_id'][:20]}...: {t['pdf_name']} ({t['status']})")

    await db.close()

asyncio.run(check())
