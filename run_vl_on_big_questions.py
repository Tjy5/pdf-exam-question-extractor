import json
from pathlib import Path
from typing import Any, Dict, List

from paddleocr import PaddleOCRVL


ROOT = Path(__file__).resolve().parent
IMG_DIR = ROOT / "pdf_images"


def iter_meta_paths() -> List[Path]:
    """遍历所有 questions_page_*/meta.json 文件。"""
    paths: List[Path] = []
    for meta_path in sorted(IMG_DIR.glob("questions_page_*/meta.json")):
        paths.append(meta_path)
    return paths


def run_vl_on_meta(meta_path: Path, pipeline: PaddleOCRVL, out_dir: Path) -> None:
    """
    对某一页的 big_questions 段落运行 PaddleOCR-VL，将 JSON 结果写入 out_dir，
    并在 meta.json 中记录 `vl_json_path`。
    """
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    big_questions: List[Dict[str, Any]] = meta.get("big_questions") or []
    if not big_questions:
        return

    changed = False
    out_dir.mkdir(parents=True, exist_ok=True)

    for bq in big_questions:
        segments = bq.get("segments") or []
        for seg in segments:
            img_path = seg.get("image")
            if not img_path or seg.get("vl_json_path"):
                continue

            img_name = Path(img_path).stem
            json_path = out_dir / f"{img_name}_vl.json"

            print(f"[PaddleOCR-VL] {meta_path.name} - {bq.get('id')} - {img_path}")
            pages = pipeline.predict(img_path)
            # 当前场景下一般每张 big_*.png 只有一页结果，这里简单地覆盖写入
            for page in pages:
                page.save_to_json(str(json_path))

            seg["vl_json_path"] = str(json_path)
            changed = True

    if changed:
        meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    pipeline = PaddleOCRVL(use_layout_detection=True)
    out_dir = IMG_DIR / "vl_output"

    for meta_path in iter_meta_paths():
        run_vl_on_meta(meta_path, pipeline, out_dir)


if __name__ == "__main__":
    main()

