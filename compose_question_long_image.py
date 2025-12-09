import json
from pathlib import Path
from typing import Any, Dict, List

from PIL import Image


ROOT = Path(".").resolve()
DEFAULT_IMG_DIR = ROOT / "pdf_images"


def page_index(page_name: str) -> int:
    try:
        return int(page_name.split("_")[-1])
    except Exception:
        return 0


def parse_args():
    import argparse

    parser = argparse.ArgumentParser(
        description="Compose cross-page question segments into a single long image."
    )
    parser.add_argument(
        "--dir",
        type=str,
        default="pdf_images",
        help="Input directory that contains questions_page_*/meta.json (default: pdf_images)",
    )
    return parser.parse_args()


def load_meta(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_meta(path: Path, meta: Dict[str, Any]) -> None:
    with path.open("w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)


def resolve_image_path(img_path_str: str, img_dir: Path) -> Path:
    """
    将 meta.json 中存储的 image 路径解析为可用的文件路径。

    - 先按原样解析（相对于当前工作目录）；
    - 再尝试拼到 img_dir.parent（通常为 pdf_images 的上一级）；
    - 如果都不存在，则返回第二种拼接结果（之后再检查 is_file）。
    """
    p = Path(img_path_str)
    if p.is_file():
        return p
    candidate = (img_dir.parent / img_path_str).resolve()
    return candidate


def compose_vertical(images: List[Image.Image]) -> Image.Image:
    """
    将多张图片按顺序竖直拼接成一张长图。
    """
    if not images:
        raise ValueError("no images to compose")

    widths = [im.width for im in images]
    heights = [im.height for im in images]

    max_width = max(widths)
    total_height = sum(heights)

    mode = images[0].mode
    if mode == "P":
        mode = "RGBA"
        images = [im.convert(mode) for im in images]

    long_img = Image.new(mode, (max_width, total_height), (255, 255, 255, 0) if "A" in mode else (255, 255, 255))

    y_offset = 0
    for im in images:
        long_img.paste(im, (0, y_offset))
        y_offset += im.height

    return long_img


def process_meta_file(meta_path: Path, img_dir: Path) -> None:
    """
    对单页的 meta.json 进行处理：
    - 为带有 segments 的小题生成 qXX_long.png，并写入 q["long_image"];
    - 为带有 segments 的资料分析大题生成 data_analysis_X_long.png，并写入 bq["combined_image"]。
    """
    meta = load_meta(meta_path)
    changed = False
    out_dir = meta_path.parent

    # 1) 小题长图（基于 questions[*].segments）
    questions: List[Dict[str, Any]] = meta.get("questions") or []
    for q in questions:
        segments = q.get("segments") or []
        if not segments:
            continue

        long_image_path_str = q.get("long_image")
        if long_image_path_str:
            existing = resolve_image_path(long_image_path_str, img_dir)
            if existing.is_file():
                continue

        img_paths: List[Path] = []
        for seg in segments:
            img_str = seg.get("image")
            if not img_str:
                continue
            img_path = resolve_image_path(img_str, img_dir)
            if img_path.is_file():
                img_paths.append(img_path)

        if not img_paths:
            continue

        images = [Image.open(p) for p in img_paths]
        try:
            long_img = compose_vertical(images)
        finally:
            for im in images:
                im.close()

        qno = q.get("qno")
        if qno is None:
            continue

        out_name = f"q{qno}_long.png"
        out_path = out_dir / out_name
        long_img.save(out_path)

        try:
            rel_path = out_path.relative_to(img_dir.parent)
        except ValueError:
            rel_path = out_path

        q["long_image"] = str(rel_path)
        changed = True

    # 2) 资料分析大题长图（基于 big_questions[*].segments）
    big_questions: List[Dict[str, Any]] = meta.get("big_questions") or []
    for bq in big_questions:
        segments = bq.get("segments") or []
        if not segments:
            continue

        combined_path_str = bq.get("combined_image")
        if combined_path_str:
            existing = resolve_image_path(combined_path_str, img_dir)
            if existing.is_file():
                continue

        img_paths: List[Path] = []
        for seg in segments:
            img_str = seg.get("image")
            if not img_str:
                continue
            img_path = resolve_image_path(img_str, img_dir)
            if img_path.is_file():
                img_paths.append(img_path)

        if not img_paths:
            continue

        images = [Image.open(p) for p in img_paths]
        try:
            long_img = compose_vertical(images)
        finally:
            for im in images:
                im.close()

        bq_id = str(bq.get("id") or "big_question")
        out_name = f"{bq_id}_long.png"
        out_path = out_dir / out_name
        long_img.save(out_path)

        try:
            rel_path = out_path.relative_to(img_dir.parent)
        except ValueError:
            rel_path = out_path

        bq["combined_image"] = str(rel_path)
        changed = True

    if changed:
        save_meta(meta_path, meta)


def main() -> None:
    args = parse_args()
    img_dir = Path(args.dir).resolve()

    if not img_dir.is_dir():
        print(f"错误: 目录不存在: {img_dir}")
        return

    meta_paths = sorted(
        img_dir.glob("questions_page_*/meta.json"),
        key=lambda p: page_index(p.parent.name.replace("questions_", "")),
    )
    if not meta_paths:
        print(f"未在目录 {img_dir} 下找到任何 questions_page_*/meta.json 文件。")
        return

    print(f"将在以下 meta.json 上生成跨页长图：")
    for m in meta_paths:
        print(f"  - {m}")

    for meta_path in meta_paths:
        process_meta_file(meta_path, img_dir)

    print("处理完成。")


if __name__ == "__main__":
    main()
