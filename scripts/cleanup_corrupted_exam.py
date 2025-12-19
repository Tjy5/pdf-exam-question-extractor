import asyncio
import sys
import os

# Add project root and backend/src to path
root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.append(root_dir)
sys.path.append(os.path.join(root_dir, 'backend', 'src'))

try:
    from backend.src.config import config
    from backend.src.db.connection import get_db_manager
except ImportError:
    from web.config import config
    from db.connection import get_db_manager

async def delete_corrupted_exam():
    db = get_db_manager(config.db_path)
    await db.init()
    
    # IDs to delete - updated after search
    exams_to_delete = []

    print("Searching for exams with corrupted names...")
    rows = await db.fetch_all("SELECT id, exam_dir_name, display_name FROM exams")
    
    target_str = "²âÊÔ"
    
    for row in rows:
        eid = row['id']
        name = row['exam_dir_name']
        display = row['display_name']
        
        print(f"Checking Exam {eid}: Name='{name}', Display='{display}'")
        
        if (name and target_str in name) or (display and target_str in display):
            print(f"  -> FOUND MATCH! Marking Exam {eid} for deletion.")
            exams_to_delete.append(eid)
            
    if not exams_to_delete:
        print(f"No exams found containing '{target_str}'")
        return

    print(f"\nFound {len(exams_to_delete)} exams to delete: {exams_to_delete}")
    
    async with db.transaction():
        for eid in exams_to_delete:
            print(f"Deleting exam {eid}...")
            # Delete related data first (though cascading delete might handle it, let's be safe)
            await db.execute("DELETE FROM exam_answers WHERE exam_id = ?", (eid,))
            await db.execute("DELETE FROM exam_questions WHERE exam_id = ?", (eid,))
            # Delete sessions
            await db.execute("DELETE FROM chat_messages WHERE session_id IN (SELECT session_id FROM chat_sessions WHERE exam_id = ?)", (eid,))
            await db.execute("DELETE FROM chat_sessions WHERE exam_id = ?", (eid,))
            # Delete exam
            await db.execute("DELETE FROM exams WHERE id = ?", (eid,))
            print(f"Exam {eid} deleted.")
            
    print("\nDeletion complete.")

if __name__ == "__main__":
    asyncio.run(delete_corrupted_exam())
