import json
import sys
import argparse
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from PIL import Image

# 导入公共模块
from common import (
    QUESTION_HEAD_PATTERN,
    page_index,
    get_ppstructure,
    layout_blocks_from_doc,
    save_meta,
    is_section_boundary_block,
    detect_section_boundaries,
    detect_continuation_blocks,
    compute_smart_crop_box,
    auto_latest_exam_dir,
)


INTRO_PATTERNS = [
    re.compile(r"资料分析"),
    re.compile(r"(根据|依据).{0,12}(资料|材料|图表)"),
    re.compile(r"回答\s*\d+\s*[-~－—]\s*\d+\s*题"),
]


def find_question_spans(
    blocks: List[Dict[str, Any]], section_boundaries: Optional[Set[int]] = None
) -> List[Dict[str, int]]:
    """
    Find spans of blocks belonging to each question, based on question-number
    headings in text blocks.

    Returns a list of dicts: [{qno, start, end}, ...] where start/end are indices
    in the blocks list (end is exclusive).
    """
    heads: List[Dict[str, int]] = []
    boundary_set: Set[int] = section_boundaries or set()
    for idx, blk in enumerate(blocks):
        if blk["label"] != "text":
            continue
        content = blk.get("content") or ""
        if not isinstance(content, str):
            content = str(content)
        m = QUESTION_HEAD_PATTERN.search(content)
        if not m:
            continue
        try:
            qno = int(m.group(1))
        except ValueError:
            continue
        heads.append({"qno": qno, "start": idx})

    spans: List[Dict[str, int]] = []
    for i, head in enumerate(heads):
        start = head["start"]
        end = heads[i + 1]["start"] if i + 1 < len(heads) else len(blocks)

        # 如果在当前题号之后、下一题号之前出现了 section boundary，
        # 则将该 boundary 视为本题的结束位置（不包含 boundary 本身）。
        if boundary_set:
            after_start = [b for b in boundary_set if start < b < end]
            if after_start:
                end = min(after_start)
        spans.append({"qno": head["qno"], "start": start, "end": end})
    return spans


def extract_questions_from_page(
    img_path: Path,
    pipeline: Any,
) -> List[Dict[str, Any]]:
    """
    Run PP-StructureV3 on a single page image and return a list of question
    structures, each containing text/table blocks and suggested crop boxes.

    使用智能裁剪边界，margin 根据页面尺寸动态计算。
    """
    img = Image.open(img_path)
    width, height = img.size
    page_size = (width, height)

    doc = pipeline.predict(str(img_path))[0]
    blocks = layout_blocks_from_doc(doc)
    section_boundaries = detect_section_boundaries(blocks)

    # 预先统计整页的页脚位置（footer/number），用于后面裁剪时避免把页脚截进去
    footer_ys: List[int] = []
    for blk in blocks:
        label = blk.get("label")
        bbox = blk.get("bbox")
        if (
            label in {"footer", "number"}
            and isinstance(bbox, (list, tuple))
            and len(bbox) == 4
        ):
            footer_ys.append(int(bbox[1]))
    footer_top: int | None = min(footer_ys) if footer_ys else None

    spans = find_question_spans(blocks, section_boundaries=section_boundaries)

    questions: List[Dict[str, Any]] = []
    for span in spans:
        q_blocks = blocks[span["start"] : span["end"]]
        if not q_blocks:
            continue

        # 使用智能裁剪边界计算
        crop_box_image = compute_smart_crop_box(
            blocks=q_blocks,
            page_size=page_size,
            footer_top=footer_top,
            use_full_width=True,
        )

        # 计算紧凑版 crop_box_blocks（基于内容边界，不含 margin）
        xs: List[int] = []
        ys: List[int] = []
        for blk in q_blocks:
            label = blk.get("label")
            bbox = blk.get("bbox")
            if (
                label in {"footer", "number", "header"}
                or not isinstance(bbox, (list, tuple))
                or len(bbox) != 4
            ):
                continue
            xs.extend([int(bbox[0]), int(bbox[2])])
            ys.extend([int(bbox[1]), int(bbox[3])])

        if not ys:
            for blk in q_blocks:
                bbox = blk.get("bbox")
                if isinstance(bbox, (list, tuple)) and len(bbox) == 4:
                    xs.extend([int(bbox[0]), int(bbox[2])])
                    ys.extend([int(bbox[1]), int(bbox[3])])

        if not ys:
            continue

        crop_box_blocks = [min(xs), min(ys), max(xs), max(ys)]

        text_blocks: List[Dict[str, Any]] = []
        table_blocks: List[Dict[str, Any]] = []
        other_blocks: List[Dict[str, Any]] = []
        for blk in q_blocks:
            if blk["label"] == "text":
                text_blocks.append(
                    {"bbox": blk["bbox"], "text": blk["content"]}
                )
            elif blk["label"] == "table":
                table_blocks.append(
                    {"bbox": blk["bbox"], "html": blk["content"]}
                )
            else:
                other_blocks.append(
                    {
                        "label": blk["label"],
                        "bbox": blk["bbox"],
                        "content": blk.get("content"),
                        "region_label": blk.get("region_label"),
                    }
                )

        questions.append(
            {
                "qno": span["qno"],
                "crop_box_image": list(crop_box_image),
                "crop_box_blocks": crop_box_blocks,
                "text_blocks": text_blocks,
                "table_blocks": table_blocks,
                "other_blocks": other_blocks,
            }
        )

    return questions


def looks_like_new_section_intro(blocks: List[Dict[str, Any]]) -> bool:
    """
    判断由若干块组成的片段是否更像“新部分/资料分析开头”，
    用于避免把整页材料误判为上一题的续接内容。
    """
    texts: List[str] = []
    for blk in blocks:
        content = blk.get("content")
        if isinstance(content, str):
            texts.append(content.strip())
    if not texts:
        return False
    blob = "".join(texts).replace("\n", "")
    return any(p.search(blob) for p in INTRO_PATTERNS)


def save_questions_for_page(
    img_path: Path, questions: List[Dict[str, Any]], base_output_dir: Path
) -> Dict[str, Any]:
    """
    Save per-question cropped images and return a JSON-serializable summary
    for this page.
    """
    img = Image.open(img_path)
    page_name = img_path.stem  # e.g. "page_6"

    # Put questions alongside source images, but不覆盖原图
    page_out_dir = base_output_dir / f"questions_{page_name}"
    page_out_dir.mkdir(parents=True, exist_ok=True)

    page_summary: Dict[str, Any] = {
        "page_name": page_name,
        "image_path": str(img_path),
        "questions": [],
    }

    for q in questions:
        qno = q["qno"]
        crop_box = q["crop_box_image"]
        crop_img = img.crop(tuple(crop_box))
        img_name = f"q{qno}.png"
        out_img_path = page_out_dir / img_name
        crop_img.save(out_img_path)

        # 存储相对路径，方便跨平台/移动
        try:
            rel_path = out_img_path.relative_to(base_output_dir.parent)
        except ValueError:
            rel_path = out_img_path

        page_summary["questions"].append(
            {
                "qno": qno,
                "image": str(rel_path),
                "crop_box_image": q["crop_box_image"],
                "crop_box_blocks": q["crop_box_blocks"],
                "text_blocks": q["text_blocks"],
                "table_blocks": q["table_blocks"],
                "other_blocks": q.get("other_blocks", []),
            }
        )

    # Save one meta JSON per page
    meta_path = page_out_dir / "meta.json"
    with meta_path.open("w", encoding="utf-8") as f:
        json.dump(page_summary, f, ensure_ascii=False, indent=2)

    return page_summary


def add_cross_page_segments(
    img_paths: List[Path],
    all_page_summaries: List[Dict[str, Any]],
    pipeline: Any,
    base_output_dir: Path,
) -> None:
    """
    处理"小题跨两页"的情况：

    - 按页顺序遍历所有 page_*.png；
    - 如果当前页顶部（第一个题号之前）存在正文块，则将这些块视为
      "上一道题的续接部分"，为上一道题裁剪一张新的续接图片；
    - 在上一页的题目条目中增加 `segments` 字段，结构与 big_questions 的 segments 类似：
        segments: [
          {"page": "page_6", "image": ".../q39.png", "box": [..]},
          {"page": "page_7", "image": ".../q39_part2.png", "box": [..]}
        ]

    说明：
    - 为兼容性考虑，只在检测到跨页续接时才新增 segments；
    - text_blocks 目前仍然只包含本页内容，如需跨页文本汇总，可在后续脚本中基于 segments 再做 OCR。
    - 改进：使用智能裁剪边界和置信度评估
    """
    if not all_page_summaries:
        return

    # 方便通过 page_name 找到对应的 summary
    summary_by_page: Dict[str, Dict[str, Any]] = {
        s["page_name"]: s for s in all_page_summaries
    }

    # 记录最近出现的"有题目"的那一道题，用于多页连续续接
    last_q_entry: Optional[Dict[str, Any]] = None
    last_q_page_name: Optional[str] = None

    # 将图片按页码顺序遍历
    sorted_img_paths = sorted(img_paths, key=lambda p: page_index(p.stem))

    for img_path in sorted_img_paths:
        page_name = img_path.stem  # page_6
        summary = summary_by_page.get(page_name)

        # 第一步：如果已经有上一道题，则尝试在当前页顶部寻找续接内容
        if last_q_entry is not None and last_q_page_name is not None:
            try:
                doc = pipeline.predict(str(img_path))[0]
            except Exception:
                doc = {}

            blocks = layout_blocks_from_doc(doc) if doc else []
            section_boundaries = detect_section_boundaries(blocks)

            # 使用改进的续接检测（返回置信度）
            cand_blocks, confidence = detect_continuation_blocks(
                blocks, section_boundaries=section_boundaries
            )

            # 只有置信度足够高时才生成续接图片
            if cand_blocks and confidence >= 0.5:
                img = Image.open(img_path)
                width, height = img.size
                page_size = (width, height)

                # 计算页脚位置
                footer_ys: List[int] = []
                for blk in blocks:
                    label = blk.get("label")
                    bbox = blk.get("bbox")
                    if (
                        label in {"footer", "number"}
                        and isinstance(bbox, (list, tuple))
                        and len(bbox) == 4
                    ):
                        footer_ys.append(int(bbox[1]))
                footer_top: Optional[int] = min(footer_ys) if footer_ys else None

                # 使用智能裁剪边界计算续接内容的裁剪框
                crop_box = compute_smart_crop_box(
                    blocks=cand_blocks,
                    page_size=page_size,
                    footer_top=footer_top,
                    use_full_width=True,
                )

                left, top, right, bottom = crop_box
                height_ratio = (bottom - top) / float(height) if height else 1.0

                # 大块材料页（如资料分析提示页）不应归为上一题续接
                if looks_like_new_section_intro(cand_blocks) or height_ratio > 0.35:
                    continue

                if right > left and bottom > top:
                    page_out_dir = base_output_dir / f"questions_{page_name}"
                    page_out_dir.mkdir(parents=True, exist_ok=True)

                    qno = last_q_entry.get("qno")
                    # 计算当前是第几个片段，用于命名 part2/part3...
                    segments: List[Dict[str, Any]] = last_q_entry.get("segments") or []
                    next_part_idx = 2 if not segments else len(segments) + 1
                    img_name = f"q{qno}_part{next_part_idx}.png"
                    out_img_path = page_out_dir / img_name

                    crop_img = img.crop(crop_box)
                    crop_img.save(out_img_path)

                    try:
                        rel_path = out_img_path.relative_to(base_output_dir.parent)
                    except ValueError:
                        rel_path = out_img_path

                    # 初始化 segments 时，把原始那一页也作为第一个片段挂进去
                    if not segments:
                        segments.append(
                            {
                                "page": last_q_page_name,
                                "image": last_q_entry.get("image"),
                                "box": last_q_entry.get("crop_box_image"),
                            }
                        )
                    segments.append(
                        {
                            "page": page_name,
                            "image": str(rel_path),
                            "box": list(crop_box),
                            "confidence": confidence,  # 记录置信度
                        }
                    )
                    last_q_entry["segments"] = segments

        # 第二步：更新"最近一道题"的指针（如果本页有题）
        if summary and summary.get("questions"):
            # 按题号顺序，本页最后一题视为"最近一道题"
            last_q_entry = summary["questions"][-1]
            last_q_page_name = page_name

    # 所有跨页信息处理完毕后，统一回写各页的 meta.json
    for page_name, summary in summary_by_page.items():
        meta_path = base_output_dir / f"questions_{page_name}" / "meta.json"
        save_meta(meta_path, summary)


def parse_args():
    parser = argparse.ArgumentParser(description="Extract questions from exam pages.")
    parser.add_argument(
        "--dir",
        type=str,
        default=None,
        help="Input directory containing page_*.png. If omitted, auto-pick latest under pdf_images/.last_processed",
    )
    parser.add_argument(
        "--skip-existing",
        action="store_true",
        help="Skip pages whose questions_page_X/meta.json already exists",
    )
    parser.add_argument(
        "pages",
        nargs="*",
        help="Specific pages to process (e.g., 6 7 or page_6.png). If empty, process all.",
    )
    return parser.parse_args()


def main() -> None:
    """
    Batch process page_*.png images.
    """
    args = parse_args()
    
    # 允许指定子目录；未指定时自动选择最近的试卷目录
    img_dir = Path(args.dir).resolve() if args.dir else auto_latest_exam_dir().resolve()

    if not img_dir.is_dir():
        print(f"错误: 目录不存在: {img_dir}")
        sys.exit(1)

    print(f"正在处理目录: {img_dir}")

    pipeline = get_ppstructure()
    all_page_summaries: List[Dict[str, Any]] = []

    img_paths: List[Path] = []
    if not args.pages:
        # 默认处理所有 page_*.png
        img_paths = sorted(img_dir.glob("page_*.png"))
    else:
        # 支持两种写法：6 7 或 page_6.png
        for arg in args.pages:
            if arg.isdigit():
                name = f"page_{arg}.png"
            else:
                name = arg
                if not name.lower().endswith(".png"):
                    name = name + ".png"
            path = img_dir / name
            if not path.is_file():
                print(f"警告: 找不到页面文件 {path}，已跳过")
                continue
            img_paths.append(path)
        img_paths.sort()

    if not img_paths:
        print("未找到任何需要处理的 page_*.png 图片。")
        return

    for img_path in img_paths:
        meta_path = img_dir / f"questions_{img_path.stem}" / "meta.json"
        if args.skip_existing and meta_path.is_file():
            print(f"跳过已存在: {img_path.name}")
            continue

        print(f"正在处理: {img_path.name}")
        questions = extract_questions_from_page(img_path, pipeline)
        if not questions:
            print(f"  - 未在该页提取到题目。")
            continue
        summary = save_questions_for_page(
            img_path=img_path,
            questions=questions,
            base_output_dir=img_dir,
        )
        all_page_summaries.append(summary)

    # 处理“小题跨两页”的续接片段（如有），会在相应题目下增加 segments 字段并更新各页 meta.json
    if all_page_summaries:
        add_cross_page_segments(
            img_paths=img_paths,
            all_page_summaries=all_page_summaries,
            pipeline=pipeline,
            base_output_dir=img_dir,
        )

    # 可选：输出一个总的 exam_questions.json
    if all_page_summaries:
        out_path = img_dir / "exam_questions.json"
        with out_path.open("w", encoding="utf-8") as f:
            json.dump(all_page_summaries, f, ensure_ascii=False, indent=2)
        print(f"处理完成！结果汇总于: {out_path}")


if __name__ == "__main__":
    main()
