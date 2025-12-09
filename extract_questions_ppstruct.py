import json
import re
import sys
import argparse
from pathlib import Path
from typing import Any, Dict, List, Optional

from PIL import Image
from paddleocr import PPStructureV3


# 题号行匹配：支持 “40.”、“40．”、“40、”，并兼顾出现在句首/换行/句号后的题号
# 示例：开头的 "45."，或者 "。46." 这类紧跟在句号后的新题号
QUESTION_HEAD_PATTERN = re.compile(r"(?:^|\n|。)\s*(\d{1,3})[\.．、]\s*")


def page_index(page_name: str) -> int:
    """
    提取 page_6, page_10 里的数字部分，用于排序。
    """
    try:
        return int(page_name.split("_")[-1])
    except Exception:
        return 0


def load_ppstructure() -> PPStructureV3:
    """
    Initialize a shared PP-StructureV3 pipeline instance.
    """
    pipeline = PPStructureV3(
        use_doc_orientation_classify=False,
        use_doc_unwarping=False,
    )
    return pipeline


def layout_blocks_from_doc(doc: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Convert PP-StructureV3 parsing_res_list into a list of plain dict blocks.
    Each block dict contains at least: index, label, region_label, bbox, content.
    """
    blocks: List[Dict[str, Any]] = []

    parsing_list = doc.get("parsing_res_list") or []
    for blk in parsing_list:
        # blk is a LayoutBlock object
        if hasattr(blk, "to_dict"):
            info = blk.to_dict()
        else:
            # Fallback: try to use its __dict__
            info = getattr(blk, "__dict__", {})

        if not info:
            continue

        label = info.get("label")
        bbox = info.get("bbox")
        content = info.get("content", "")

        if not bbox or label is None:
            continue

        blocks.append(
            {
                "index": info.get("index", 0),
                "label": label,
                "region_label": info.get("region_label"),
                "bbox": bbox,
                "content": content if isinstance(content, str) else str(content),
            }
        )

    # Ensure blocks are in reading order (index and then top y as a tiebreaker)
    blocks.sort(key=lambda b: (b["index"], b["bbox"][1], b["bbox"][0]))
    return blocks


def find_question_spans(blocks: List[Dict[str, Any]]) -> List[Dict[str, int]]:
    """
    Find spans of blocks belonging to each question, based on question-number
    headings in text blocks.

    Returns a list of dicts: [{qno, start, end}, ...] where start/end are indices
    in the blocks list (end is exclusive).
    """
    heads: List[Dict[str, int]] = []
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
        spans.append({"qno": head["qno"], "start": start, "end": end})
    return spans


SECTION_HEAD_KEYWORDS = ["资料分析", "判断推理", "言语理解与表达", "数量关系"]


def detect_continuation_blocks(
    blocks: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    在当前页的版面块中，找到“出现在第一个题号之前的正文块”，
    作为上一题跨页续接内容的候选。

    - 忽略 header/footer/number 等块；
    - 一旦遇到第一个题号行，就停止。
    """
    # 如果当前页已经出现了新的大题/部分标题（如“资料分析”“判断推理”等），
    # 则不再视为上一题的跨页续接，直接返回空。
    for blk in blocks:
        if blk.get("label") != "text":
            continue
        content = blk.get("content") or ""
        if isinstance(content, str) and any(
            key in content for key in SECTION_HEAD_KEYWORDS
        ):
            return []

    first_head_idx: Optional[int] = None
    for idx, blk in enumerate(blocks):
        if blk.get("label") != "text":
            continue
        content = blk.get("content") or ""
        if not isinstance(content, str):
            content = str(content)
        if QUESTION_HEAD_PATTERN.search(content):
            first_head_idx = idx
            break

    candidates: List[Dict[str, Any]] = []
    for idx, blk in enumerate(blocks):
        if first_head_idx is not None and idx >= first_head_idx:
            break
        label = blk.get("label")
        bbox = blk.get("bbox")
        if (
            label in {"footer", "number", "header"}
            or not isinstance(bbox, (list, tuple))
            or len(bbox) != 4
        ):
            continue
        # 如果是新大题/新部分的标题（例如“资料分析”“判断推理”等），不视为上一题的续接内容
        content = blk.get("content") or ""
        if isinstance(content, str) and any(
            key in content for key in SECTION_HEAD_KEYWORDS
        ):
            continue
        candidates.append(blk)

    return candidates


def extract_questions_from_page(
    img_path: Path,
    pipeline: PPStructureV3,
    margin_y: int = 5,
    margin_x: int = 8,
) -> List[Dict[str, Any]]:
    """
    Run PP-StructureV3 on a single page image and return a list of question
    structures, each containing text/table blocks and suggested crop boxes.
    """
    img = Image.open(img_path)
    width, height = img.size

    doc = pipeline.predict(str(img_path))[0]
    blocks = layout_blocks_from_doc(doc)

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

    spans = find_question_spans(blocks)

    questions: List[Dict[str, Any]] = []
    for span in spans:
        q_blocks = blocks[span["start"] : span["end"]]
        if not q_blocks:
            continue

        # Compute vertical span of all blocks in this question
        # 注意：这里刻意排除 header/footer/number 等块，避免把页眉页脚算进题目高度
        ys: List[int] = []
        xs: List[int] = []
        for blk in q_blocks:
            label = blk.get("label")
            bbox = blk.get("bbox")
            if (
                label in {"footer", "number", "header"}
                or not isinstance(bbox, (list, tuple))
                or len(bbox) != 4
            ):
                continue
            x1, y1, x2, y2 = bbox
            xs.extend([x1, x2])
            ys.extend([y1, y2])

        # 极端情况下，如果上面的过滤导致没有有效块，则退回到原始 q_blocks 全量计算
        if not ys:
            for blk in q_blocks:
                bbox = blk.get("bbox")
                if (
                    not isinstance(bbox, (list, tuple))
                    or len(bbox) != 4
                ):
                    continue
                x1, y1, x2, y2 = bbox
                xs.extend([x1, x2])
                ys.extend([y1, y2])

        if not ys:
            continue

        top = max(0, min(ys) - margin_y)
        bottom = min(height, max(ys) + margin_y)

        # 如果整页识别到了 footer/number，则再用 footer_top 把题目底部“卡”在页脚上方
        if footer_top is not None:
            bottom = min(bottom, max(0, footer_top - 5))

        min_x, max_x = min(xs), max(xs)
        left = max(0, min_x - margin_x)
        right = min(width, max_x + margin_x)
        # fallback: if宽度异常（极端情况），退回整页宽
        if right <= left:
            left, right = 0, width

        crop_box_image = [left, top, right, bottom]
        crop_box_blocks = [min_x, min(ys), max_x, max(ys)]

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
                "crop_box_image": crop_box_image,
                "crop_box_blocks": crop_box_blocks,
                "text_blocks": text_blocks,
                "table_blocks": table_blocks,
                "other_blocks": other_blocks,
            }
        )

    return questions


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
    pipeline: PPStructureV3,
    base_output_dir: Path,
) -> None:
    """
    处理“小题跨两页”的情况：

    - 按页顺序遍历所有 page_*.png；
    - 如果当前页顶部（第一个题号之前）存在正文块，则将这些块视为
      “上一道题的续接部分”，为上一道题裁剪一张新的续接图片；
    - 在上一页的题目条目中增加 `segments` 字段，结构与 big_questions 的 segments 类似：
        segments: [
          {"page": "page_6", "image": ".../q39.png", "box": [..]},
          {"page": "page_7", "image": ".../q39_part2.png", "box": [..]}
        ]

    说明：
    - 为兼容性考虑，只在检测到跨页续接时才新增 segments；
    - text_blocks 目前仍然只包含本页内容，如需跨页文本汇总，可在后续脚本中基于 segments 再做 OCR。
    """
    if not all_page_summaries:
        return

    # 方便通过 page_name 找到对应的 summary
    summary_by_page: Dict[str, Dict[str, Any]] = {
        s["page_name"]: s for s in all_page_summaries
    }

    # 记录最近出现的“有题目”的那一道题，用于多页连续续接
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
            cand_blocks = detect_continuation_blocks(blocks)
            if cand_blocks:
                # 计算这些续接块的裁剪范围
                img = Image.open(img_path)
                width, height = img.size

                xs: List[int] = []
                ys: List[int] = []
                for blk in cand_blocks:
                    bbox = blk.get("bbox")
                    if (
                        not isinstance(bbox, (list, tuple))
                        or len(bbox) != 4
                    ):
                        continue
                    x1, y1, x2, y2 = bbox
                    xs.extend([int(x1), int(x2)])
                    ys.extend([int(y1), int(y2)])

                if xs and ys:
                    # 同样考虑页脚，避免把页码截进去
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

                    margin_y = 5
                    margin_x = 8
                    top = max(0, min(ys) - margin_y)
                    bottom = min(height, max(ys) + margin_y)
                    if footer_top is not None:
                        bottom = min(bottom, max(0, footer_top - 5))

                    min_x, max_x = min(xs), max(xs)
                    left = max(0, min_x - margin_x)
                    right = min(width, max_x + margin_x)
                    if right > left and bottom > top:
                        crop_box = [left, top, right, bottom]
                        page_out_dir = base_output_dir / f"questions_{page_name}"
                        page_out_dir.mkdir(parents=True, exist_ok=True)

                        qno = last_q_entry.get("qno")
                        # 计算当前是第几个片段，用于命名 part2/part3...
                        segments: List[Dict[str, Any]] = last_q_entry.get("segments") or []
                        next_part_idx = 2 if not segments else len(segments) + 1
                        img_name = f"q{qno}_part{next_part_idx}.png"
                        out_img_path = page_out_dir / img_name

                        crop_img = img.crop(tuple(crop_box))
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
                                "box": crop_box,
                            }
                        )
                        last_q_entry["segments"] = segments

        # 第二步：更新“最近一道题”的指针（如果本页有题）
        if summary and summary.get("questions"):
            # 按题号顺序，本页最后一题视为“最近一道题”
            last_q_entry = summary["questions"][-1]
            last_q_page_name = page_name

    # 所有跨页信息处理完毕后，统一回写各页的 meta.json
    for page_name, summary in summary_by_page.items():
        meta_path = base_output_dir / f"questions_{page_name}" / "meta.json"
        meta_path.parent.mkdir(parents=True, exist_ok=True)
        with meta_path.open("w", encoding="utf-8") as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)


def parse_args():
    parser = argparse.ArgumentParser(description="Extract questions from exam pages.")
    parser.add_argument(
        "--dir", 
        type=str, 
        default="pdf_images", 
        help="Input directory containing page_*.png (default: pdf_images)"
    )
    parser.add_argument(
        "pages", 
        nargs="*", 
        help="Specific pages to process (e.g., 6 7 or page_6.png). If empty, process all."
    )
    return parser.parse_args()


def main() -> None:
    """
    Batch process page_*.png images.
    """
    args = parse_args()
    
    # 允许指定子目录
    img_dir = Path(args.dir).resolve()

    if not img_dir.is_dir():
        print(f"错误: 目录不存在: {img_dir}")
        sys.exit(1)

    print(f"正在处理目录: {img_dir}")

    pipeline = load_ppstructure()
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
