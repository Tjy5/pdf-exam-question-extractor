import argparse
import json
from pathlib import Path
from typing import Any, Dict, List

from paddleocr import PaddleOCRVL

from common import iter_meta_paths, resolve_image_path, auto_latest_exam_dir


ROOT = Path(__file__).resolve().parent


def run_vl_on_meta(
    meta_path: Path, pipeline: PaddleOCRVL, out_dir: Path, img_dir: Path
) -> None:
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

            img_abs = resolve_image_path(str(img_path), img_dir.parent)
            if not img_abs.is_file():
                print(f"[VL][WARN] 找不到图片: {img_path}（解析到 {img_abs}），已跳过")
                continue

            img_name = Path(img_path).stem
            json_path = out_dir / f"{img_name}_vl.json"

            print(f"[PaddleOCR-VL] {meta_path.name} - {bq.get('id')} - {img_abs}")
            pages = pipeline.predict(str(img_abs))
            # 当前场景下一般每张 big_*.png 只有一页结果，这里简单地覆盖写入
            for page in pages:
                page.save_to_json(str(json_path))

            seg["vl_json_path"] = str(json_path)
            changed = True

    if changed:
        meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run PaddleOCR-VL on big questions and write JSON outputs"
    )
    parser.add_argument(
        "--dir",
        type=str,
        default=None,
        help="Directory containing questions_page_*/meta.json (可指向具体试卷子目录); if omitted auto-select latest under pdf_images",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    img_dir = Path(args.dir).resolve() if args.dir else auto_latest_exam_dir().resolve()
    if not img_dir.is_dir():
        raise SystemExit(f"目录不存在: {img_dir}")

    pipeline = PaddleOCRVL(use_layout_detection=True)
    out_dir = img_dir / "vl_output"

    for meta_path in iter_meta_paths(img_dir):
        run_vl_on_meta(meta_path, pipeline, out_dir, img_dir)


if __name__ == "__main__":
    main()
