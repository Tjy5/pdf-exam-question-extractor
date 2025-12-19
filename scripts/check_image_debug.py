import asyncio
import sys
import os
from pathlib import Path

# Add project root and backend/src to path
root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.append(root_dir)
# Also add backend/src to allow direct imports if needed, though fully qualified is better
sys.path.append(os.path.join(root_dir, 'backend', 'src'))

try:
    from backend.src.config import config
    from backend.src.db.connection import get_db_manager
    from backend.src.common.types import LEGACY_PDF_IMAGES_DIR
except ImportError:
    # Try alternate import style if package structure is different
    from web.config import config
    from db.connection import get_db_manager
    from common.types import LEGACY_PDF_IMAGES_DIR

async def check_image(exam_id, question_no):
    db = get_db_manager(config.db_path)
    await db.init()
    print(f"Checking exam {exam_id}, question {question_no}...")
    
    # Check exam
    exam = await db.fetch_one("SELECT * FROM exams WHERE id = ?", (exam_id,))
    if not exam:
        print(f"Exam {exam_id} not found")
        return

    print(f"Exam found: {exam['exam_dir_name']}")
    
    # Check question
    question = await db.fetch_one(
        "SELECT * FROM exam_questions WHERE exam_id = ? AND question_no = ?", 
        (exam_id, question_no)
    )
    if not question:
        print(f"Question {exam_id}-{question_no} not found in DB")
        return

    image_filename = question['image_filename']
    print(f"Question found. Image filename: {image_filename}")
    
    if not image_filename:
        print("Image filename is empty/null")
        return

    # Check file
    exam_dir = LEGACY_PDF_IMAGES_DIR / exam['exam_dir_name']
    questions_dir = exam_dir / "all_questions"
    image_path = questions_dir / image_filename
    
    print(f"Checking file path: {image_path}")
    if image_path.exists():
        print("File exists!")
    else:
        print("File DOES NOT exist!")

if __name__ == "__main__":
    if len(sys.path) < 2:
        print(" Usage: python check_image_debug.py <exam_id> <question_no>")
        # Default to checking exam 1, question 1 if no args
        asyncio.run(check_image(1, 1))
    else:
        # Just run the default check for now to see if it works
        asyncio.run(check_image(1, 1))
