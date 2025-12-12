import json
from pathlib import Path
from typing import Any, Dict, List

from paddleocr import PPChatOCRv4Doc

from run_chatocr_on_big_questions import load_chat_bot_config, run_chatocr_on_meta
from common import iter_meta_paths


ROOT = Path(__file__).resolve().parent
IMG_DIR = ROOT / "test2" / "pdf_images"


def main() -> None:
    chat_bot_config: Dict[str, Any] = load_chat_bot_config()
    pipeline = PPChatOCRv4Doc()

    for meta_path in iter_meta_paths(IMG_DIR):
        run_chatocr_on_meta(meta_path, pipeline, chat_bot_config, IMG_DIR)


if __name__ == "__main__":
    main()
