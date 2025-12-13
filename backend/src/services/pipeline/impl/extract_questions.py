"""
extract_questions.py - 题目提取核心逻辑

使用 PP-StructureV3 从页面图片中检测并提取题目。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from PIL import Image

from ....common import (
    QUESTION_HEAD_PATTERN,
    load_meta,
    save_meta,
    layout_blocks_from_doc,
    is_section_boundary_block,
    detect_section_boundaries,
    detect_continuation_blocks,
    compute_smart_crop_box,
)


# 资料分析开头提示模式
INTRO_PATTERNS = [
    re.compile(r"资料分析"),
    re.compile(r"(根据|依据).{0,12}(资料|材料|图表)"),
    re.compile(r"回答\s*\d+\s*[-~－—]\s*\d+\s*题"),
]


def find_question_spans(
    blocks: List[Dict[str, Any]], section_boundaries: Optional[Set[int]] = None
) -> List[Dict[str, int]]:
    """
    Find spans of blocks belonging to each question.

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

        if boundary_set:
            after_start = [b for b in boundary_set if start < b < end]
            if after_start:
                end = min(after_start)
        spans.append({"qno": head["qno"], "start": start, "end": end})

    return spans


def extract_questions_from_page(
    img_path: Path,
    pipeline: Any,
    workdir: Optional[Path] = None,
    use_cache: bool = True,
) -> List[Dict[str, Any]]:
    """
    Run PP-StructureV3 on a single page image and return a list of question structures.

    Args:
        img_path: Path to the page image
        pipeline: PP-StructureV3 pipeline instance
        workdir: Working directory for OCR cache (if None, no caching)
        use_cache: Whether to use/save OCR cache

    Returns:
        List of question dictionaries with crop boxes, text/table blocks
    """
    from .ocr_cache import run_ocr_with_cache, save_ocr_cache

    img = Image.open(img_path)
    width, height = img.size
    page_size = (width, height)

    # Use OCR cache if workdir is provided
    if workdir and use_cache:
        blocks, _ = run_ocr_with_cache(pipeline, img_path, workdir)
    else:
        doc = pipeline.predict(str(img_path))[0]
        blocks = layout_blocks_from_doc(doc)
        # Save to cache if workdir provided
        if workdir:
            save_ocr_cache(workdir, img_path.stem, blocks, page_size)
    section_boundaries = detect_section_boundaries(blocks)

    # 获取页脚位置
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

    spans = find_question_spans(blocks, section_boundaries=section_boundaries)

    questions: List[Dict[str, Any]] = []
    for span in spans:
        q_blocks = blocks[span["start"] : span["end"]]
        if not q_blocks:
            continue

        # 智能裁剪边界计算
        crop_box_image = compute_smart_crop_box(
            blocks=q_blocks,
            page_size=page_size,
            footer_top=footer_top,
            use_full_width=True,
        )

        # 紧凑版 crop_box_blocks
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
                text_blocks.append({"bbox": blk["bbox"], "text": blk["content"]})
            elif blk["label"] == "table":
                table_blocks.append({"bbox": blk["bbox"], "html": blk["content"]})
            else:
                other_blocks.append({
                    "label": blk["label"],
                    "bbox": blk["bbox"],
                    "content": blk.get("content"),
                    "region_label": blk.get("region_label"),
                })

        questions.append({
            "qno": span["qno"],
            "crop_box_image": list(crop_box_image),
            "crop_box_blocks": crop_box_blocks,
            "text_blocks": text_blocks,
            "table_blocks": table_blocks,
            "other_blocks": other_blocks,
        })

    return questions


def looks_like_new_section_intro(blocks: List[Dict[str, Any]]) -> bool:
    """判断片段是否像新部分/资料分析开头。"""
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
    Save per-question cropped images and return a JSON-serializable summary.

    Args:
        img_path: Path to the page image
        questions: List of question dictionaries
        base_output_dir: Base output directory (typically the exam workdir)

    Returns:
        Page summary dictionary
    """
    img = Image.open(img_path)
    page_name = img_path.stem

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

        try:
            rel_path = out_img_path.relative_to(base_output_dir.parent)
        except ValueError:
            rel_path = out_img_path

        page_summary["questions"].append({
            "qno": qno,
            "image": str(rel_path),
            "crop_box_image": q["crop_box_image"],
            "crop_box_blocks": q["crop_box_blocks"],
            "text_blocks": q["text_blocks"],
            "table_blocks": q["table_blocks"],
            "other_blocks": q.get("other_blocks", []),
        })

    meta_path = page_out_dir / "meta.json"
    with meta_path.open("w", encoding="utf-8") as f:
        json.dump(page_summary, f, ensure_ascii=False, indent=2)

    return page_summary


def is_valid_meta(meta_path: Path) -> bool:
    """Check if a meta.json file exists and has questions."""
    if not meta_path.is_file():
        return False
    try:
        with meta_path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return bool(data.get("questions"))
    except Exception:
        return False


def add_cross_page_segments(
    img_paths: List[Path],
    all_page_summaries: List[Dict[str, Any]],
    pipeline: Any,
    base_output_dir: Path,
    log: Optional[Callable[[str], None]] = None,
) -> None:
    """
    处理小题跨两页的续接情况。

    为上一道题裁剪续接图片并添加 segments 字段。
    """
    from .ocr_cache import run_ocr_with_cache, has_ocr_cache

    log_fn = log or (lambda m: None)

    if not all_page_summaries:
        return

    summary_by_page: Dict[str, Dict[str, Any]] = {
        s["page_name"]: s for s in all_page_summaries
    }

    last_q_entry: Optional[Dict[str, Any]] = None
    last_q_page_name: Optional[str] = None

    # page_index helper
    def _page_index(name: str) -> int:
        try:
            return int(name.split("_")[-1])
        except (ValueError, IndexError):
            return 0

    sorted_img_paths = sorted(img_paths, key=lambda p: _page_index(p.stem))
    total_pages = len(sorted_img_paths)

    log_fn(f"[跨页检测] 开始处理 {total_pages} 页...")

    for idx, img_path in enumerate(sorted_img_paths):
        page_name = img_path.stem
        summary = summary_by_page.get(page_name)

        if last_q_entry is not None and last_q_page_name is not None:
            # Check if OCR cache exists
            cache_exists = has_ocr_cache(base_output_dir, page_name)
            if not cache_exists:
                log_fn(f"  [跨页] {page_name} 缓存不存在，执行OCR...")

            # Use OCR cache
            try:
                blocks, _ = run_ocr_with_cache(pipeline, img_path, base_output_dir)
            except Exception:
                blocks = []
            section_boundaries = detect_section_boundaries(blocks)

            cand_blocks, confidence = detect_continuation_blocks(
                blocks, section_boundaries=section_boundaries
            )

            if cand_blocks and confidence >= 0.5:
                img = Image.open(img_path)
                width, height = img.size
                page_size = (width, height)

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

                crop_box = compute_smart_crop_box(
                    blocks=cand_blocks,
                    page_size=page_size,
                    footer_top=footer_top,
                    use_full_width=True,
                )

                left, top, right, bottom = crop_box
                height_ratio = (bottom - top) / float(height) if height else 1.0

                if looks_like_new_section_intro(cand_blocks) or height_ratio > 0.35:
                    pass
                elif right > left and bottom > top:
                    page_out_dir = base_output_dir / f"questions_{page_name}"
                    page_out_dir.mkdir(parents=True, exist_ok=True)

                    qno = last_q_entry.get("qno")
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

                    if not segments:
                        segments.append({
                            "page": last_q_page_name,
                            "image": last_q_entry.get("image"),
                            "box": last_q_entry.get("crop_box_image"),
                        })
                    segments.append({
                        "page": page_name,
                        "image": str(rel_path),
                        "box": list(crop_box),
                        "confidence": confidence,
                    })
                    last_q_entry["segments"] = segments

        if summary and summary.get("questions"):
            last_q_entry = summary["questions"][-1]
            last_q_page_name = page_name

    log_fn(f"[跨页检测] 完成，回写 meta.json...")

    # 回写各页 meta.json
    for page_name, summary in summary_by_page.items():
        meta_path = base_output_dir / f"questions_{page_name}" / "meta.json"
        if meta_path.parent.exists():
            with meta_path.open("w", encoding="utf-8") as f:
                json.dump(summary, f, ensure_ascii=False, indent=2)


def run_extract_questions(
    img_dir: Path,
    pipeline: Any,
    skip_existing: bool = True,
    pages: Optional[List[str]] = None,
    log: Optional[Callable[[str], None]] = None,
    parallel: bool = False,
    max_workers: int = 4,
    progress_callback: Optional[Callable[[int, int, str, str], None]] = None,
) -> bool:
    """
    主入口：从页面图片中提取题目。

    Args:
        img_dir: 试卷目录（包含 page_*.png）
        pipeline: PP-StructureV3 pipeline 实例
        skip_existing: 是否跳过已存在的有效结果
        pages: 指定要处理的页面列表（为空则处理全部）
        log: 日志回调函数
        parallel: 是否启用并行处理
        max_workers: 并行 worker 数量
        progress_callback: 进度回调 (done, total, status, page_name)

    Returns:
        处理是否成功
    """
    from ....services.parallel_extraction import ParallelPageProcessor

    log_fn = log or (lambda m: None)
    img_dir = Path(img_dir)

    # 收集页面图片
    page_paths = sorted(img_dir.glob("page_*.png"))
    if pages:
        wanted = {str(p) for p in pages}
        page_paths = [p for p in page_paths if p.stem in wanted or p.name in wanted]

    if not page_paths:
        log_fn("未找到任何 page_*.png 图片")
        return False

    if parallel:
        processor = ParallelPageProcessor(
            max_workers=max_workers,
            pipeline=pipeline,
        )
        processor.set_extraction_functions(
            extract_fn=extract_questions_from_page,
            save_fn=save_questions_for_page,
            is_valid_meta_fn=is_valid_meta,
        )
        results = processor.process_pages_parallel(
            img_paths=page_paths,
            base_output_dir=img_dir,
            skip_existing=skip_existing,
            progress_callback=progress_callback,
            log=log_fn,
        )
        all_page_summaries = [r.get("summary") for r in results if r.get("summary")]
    else:
        all_page_summaries: List[Dict[str, Any]] = []
        total = len(page_paths)

        for idx, img_path in enumerate(page_paths):
            page_name = img_path.stem
            meta_path = img_dir / f"questions_{page_name}" / "meta.json"

            if skip_existing and is_valid_meta(meta_path):
                log_fn(f"  [跳过] {page_name}")
                if progress_callback:
                    progress_callback(idx + 1, total, "skipped", page_name)
                try:
                    with meta_path.open("r", encoding="utf-8") as f:
                        all_page_summaries.append(json.load(f))
                except Exception:
                    pass
                continue

            log_fn(f"  [处理] {page_name}")
            questions = extract_questions_from_page(img_path, pipeline, workdir=img_dir)

            if not questions:
                log_fn(f"    未检测到题目")
                if progress_callback:
                    progress_callback(idx + 1, total, "empty", page_name)
                continue

            summary = save_questions_for_page(
                img_path=img_path,
                questions=questions,
                base_output_dir=img_dir,
            )
            all_page_summaries.append(summary)

            if progress_callback:
                progress_callback(idx + 1, total, "success", page_name)

    # 处理跨页续接
    if all_page_summaries:
        add_cross_page_segments(
            img_paths=page_paths,
            all_page_summaries=all_page_summaries,
            pipeline=pipeline,
            base_output_dir=img_dir,
            log=log_fn,
        )

    return True
