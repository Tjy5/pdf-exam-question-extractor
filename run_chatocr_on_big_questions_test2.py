import json
from pathlib import Path
from typing import Any, Dict, List

from paddleocr import PPChatOCRv4Doc

from run_chatocr_on_big_questions import load_chat_bot_config, run_chatocr_on_meta


ROOT = Path(__file__).resolve().parent
IMG_DIR = ROOT / "test2" / "pdf_images"


def iter_meta_paths() -> List[Path]:
    """遍历 test2 中的 questions_page_*/meta.json 文件。"""
    return sorted(IMG_DIR.glob("questions_page_*/meta.json"))


def main() -> None:
    chat_bot_config: Dict[str, Any] = load_chat_bot_config()
    pipeline = PPChatOCRv4Doc()

    for meta_path in iter_meta_paths():
        run_chatocr_on_meta(meta_path, pipeline, chat_bot_config)


if __name__ == "__main__":
    main()

