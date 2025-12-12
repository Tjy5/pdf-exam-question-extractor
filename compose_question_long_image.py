from pathlib import Path
from typing import Any, Dict, List

from PIL import Image

# 导入公共模块
from common import (
    page_index,
    load_meta,
    save_meta,
    resolve_image_path,
    compose_vertical,
    iter_meta_paths,
    auto_latest_exam_dir,
)


def parse_args():
    import argparse

    parser = argparse.ArgumentParser(
        description="Compose cross-page question segments into a single long image."
    )
    parser.add_argument(
        "--dir",
        type=str,
        default=None,
        help="Directory that contains questions_page_*/meta.json; if omitted auto-select latest under pdf_images",
    )
    return parser.parse_args()


def process_meta_file(meta_path: Path, img_dir: Path):
    """
    对单页的 meta.json 进行处理：
    - 为带有 segments 的小题生成 qXX_long.png，并写入 q["long_image"];
    - 为带有 segments 的资料分析大题生成 data_analysis_X_long.png，并写入 bq["combined_image"]。
    返回：([缺失长图的题号], [缺失大题ID])
    """
    meta = load_meta(meta_path)
    changed = False
    out_dir = meta_path.parent
    missing_q: List[int] = []
    missing_bq: List[str] = []

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
            qno = q.get("qno")
            if isinstance(qno, int):
                missing_q.append(qno)
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
            bid = str(bq.get("id") or "big_question")
            missing_bq.append(bid)
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

    return missing_q, missing_bq


def main() -> None:
    args = parse_args()
    img_dir = Path(args.dir).resolve() if args.dir else auto_latest_exam_dir().resolve()

    if not img_dir.is_dir():
        print(f"错误: 目录不存在: {img_dir}")
        return

    meta_paths = iter_meta_paths(img_dir)
    if not meta_paths:
        print(f"未在目录 {img_dir} 下找到任何 questions_page_*/meta.json 文件。")
        return

    print(f"将在以下 meta.json 上生成跨页长图：")
    for m in meta_paths:
        print(f"  - {m}")

    missing_q_all: List[int] = []
    missing_bq_all: List[str] = []

    for meta_path in meta_paths:
        mq, mbq = process_meta_file(meta_path, img_dir)
        if mq:
            missing_q_all.extend(mq)
        if mbq:
            missing_bq_all.extend(mbq)

    if missing_q_all:
        uniq = sorted(set(missing_q_all))
        print(f"[warn] 未能生成长图的小题: {uniq}")
    if missing_bq_all:
        uniq = sorted(set(missing_bq_all))
        print(f"[warn] 未能生成长图的大题: {uniq}")

    print("处理完成。")


if __name__ == "__main__":
    main()
