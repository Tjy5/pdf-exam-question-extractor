import json
from pathlib import Path
from typing import Any, Dict, List

from paddleocr import PaddleOCRVL

from run_vl_on_big_questions import run_vl_on_meta
from common import iter_meta_paths


ROOT = Path(__file__).resolve().parent
IMG_DIR = ROOT / "test2" / "pdf_images"


def main() -> None:
    pipeline = PaddleOCRVL(use_layout_detection=True)
    out_dir = IMG_DIR / "vl_output"

    for meta_path in iter_meta_paths(IMG_DIR):
        run_vl_on_meta(meta_path, pipeline, out_dir, IMG_DIR)


if __name__ == "__main__":
    main()
