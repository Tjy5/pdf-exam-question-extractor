import json
from pathlib import Path
from typing import Any, Dict, List

from paddleocr import PaddleOCRVL

from run_vl_on_big_questions import run_vl_on_meta


ROOT = Path(__file__).resolve().parent
IMG_DIR = ROOT / "test2" / "pdf_images"


def iter_meta_paths() -> List[Path]:
    """遍历 test2 中的 questions_page_*/meta.json 文件。"""
    return sorted(IMG_DIR.glob("questions_page_*/meta.json"))


def main() -> None:
    pipeline = PaddleOCRVL(use_layout_detection=True)
    out_dir = IMG_DIR / "vl_output"

    for meta_path in iter_meta_paths():
        run_vl_on_meta(meta_path, pipeline, out_dir)


if __name__ == "__main__":
    main()

