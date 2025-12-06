import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List

from PIL import Image
from paddleocr import PPStructureV3


# 题号行匹配：支持 “40.”、“40．”、“40、”
QUESTION_HEAD_PATTERN = re.compile(r"^\s*(\d{1,3})[\.．、]\s*")


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
        m = QUESTION_HEAD_PATTERN.match(blk["content"])
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

        page_summary["questions"].append(
            {
                "qno": qno,
                "image": str(out_img_path),
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


def main() -> None:
    """
    Batch process page_*.png images under ./pdf_images.

    默认：处理所有 `page_*.png`。
    如果在命令行传入参数，则只处理指定页面，例如：

        python extract_questions_ppstruct.py 6 7
        python extract_questions_ppstruct.py page_6.png page_7.png

    - Use PP-StructureV3 做版面解析
    - 自动按题号切题
    - 为每页保存 questions_{page_name} 目录下的题目图片和 meta.json

    后续如果要整套卷子的结构化数据，可以再把所有 meta.json 汇总。
    """
    root = Path(".").resolve()
    img_dir = root / "pdf_images"

    if not img_dir.is_dir():
        raise SystemExit(f"目录不存在: {img_dir}")

    # 不动原始图片，只在 pdf_images 下创建 questions_* 子目录
    pipeline = load_ppstructure()

    all_page_summaries: List[Dict[str, Any]] = []

    # 根据命令行参数决定要处理哪些页面
    argv = sys.argv[1:]
    img_paths: List[Path] = []
    if not argv:
        # 默认处理所有 page_*.png
        img_paths = sorted(img_dir.glob("page_*.png"))
    else:
        # 支持两种写法：
        #   6 7            -> page_6.png, page_7.png
        #   page_6.png ... -> 直接使用给定文件名
        for arg in argv:
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

    for img_path in img_paths:
        questions = extract_questions_from_page(img_path, pipeline)
        if not questions:
            continue
        summary = save_questions_for_page(
            img_path=img_path,
            questions=questions,
            base_output_dir=img_dir,
        )
        all_page_summaries.append(summary)

    # 可选：输出一个总的 exam_questions.json
    if all_page_summaries:
        out_path = img_dir / "exam_questions.json"
        with out_path.open("w", encoding="utf-8") as f:
            json.dump(all_page_summaries, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
