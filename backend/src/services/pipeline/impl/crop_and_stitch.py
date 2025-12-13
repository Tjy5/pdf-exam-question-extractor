"""
crop_and_stitch.py - 裁剪拼接核心逻辑

根据 structure.json 裁剪题目图片，生成最终的输出图片。
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from PIL import Image

from ....common import page_index, compose_vertical
from .structure_detection import (
    StructureDoc,
    QuestionNode,
    BigQuestion,
    BBox,
    load_structure_doc,
)


def get_all_questions_dir(workdir: Path) -> Path:
    """获取最终输出目录。"""
    output_dir = workdir / "all_questions"
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


def crop_question_image(
    workdir: Path,
    question: QuestionNode,
) -> Optional[Image.Image]:
    """
    裁剪单道题目的图片。

    如果题目跨多页，则垂直拼接。
    """
    if not question.bboxes:
        return None

    images: List[Image.Image] = []

    # 按页面分组 bboxes
    page_to_bboxes: Dict[str, List[BBox]] = {}
    for bbox in question.bboxes:
        page_to_bboxes.setdefault(bbox.page, []).append(bbox)

    # 按页面顺序处理
    sorted_pages = sorted(page_to_bboxes.keys(), key=page_index)

    for page_name in sorted_pages:
        page_bboxes = page_to_bboxes[page_name]
        page_image_path = workdir / f"{page_name}.png"

        if not page_image_path.is_file():
            continue

        with Image.open(page_image_path) as page_img:
            # 计算该页面的合并边界框
            min_x = min(b.x1 for b in page_bboxes)
            min_y = min(b.y1 for b in page_bboxes)
            max_x = max(b.x2 for b in page_bboxes)
            max_y = max(b.y2 for b in page_bboxes)

            # 使用全宽
            crop_box = (0, min_y, page_img.width, max_y)

            cropped = page_img.crop(crop_box)
            images.append(cropped.copy())

    if not images:
        return None

    if len(images) == 1:
        return images[0]

    # 垂直拼接
    return compose_vertical(images)


def crop_big_question_image(
    workdir: Path,
    big_question: BigQuestion,
    all_questions: Dict[str, QuestionNode],
) -> Optional[Image.Image]:
    """
    裁剪资料分析大题的图片。

    包含材料区域和所有子题，垂直拼接。
    """
    images: List[Image.Image] = []

    # 收集所有相关的 bboxes（按页面和位置排序）
    all_bboxes: List[Tuple[str, int, BBox]] = []

    # 添加材料区域
    for bbox in big_question.material_bboxes:
        all_bboxes.append((bbox.page, bbox.y1, bbox))

    # 添加子题
    for sub_id in big_question.sub_question_ids:
        sub_q = all_questions.get(sub_id)
        if sub_q:
            for bbox in sub_q.bboxes:
                all_bboxes.append((bbox.page, bbox.y1, bbox))

    if not all_bboxes:
        # 如果没有单独的 bboxes，尝试从页面范围裁剪
        return crop_from_page_span(workdir, big_question)

    # 按页面和 y 坐标排序
    all_bboxes.sort(key=lambda x: (page_index(x[0]), x[1]))

    # 按页面分组
    page_to_bboxes: Dict[str, List[BBox]] = {}
    for page_name, _, bbox in all_bboxes:
        page_to_bboxes.setdefault(page_name, []).append(bbox)

    # 按页面顺序裁剪
    sorted_pages = sorted(page_to_bboxes.keys(), key=page_index)

    for page_name in sorted_pages:
        page_bboxes = page_to_bboxes[page_name]
        page_image_path = workdir / f"{page_name}.png"

        if not page_image_path.is_file():
            continue

        with Image.open(page_image_path) as page_img:
            # 计算该页面的合并边界框
            min_y = min(b.y1 for b in page_bboxes)
            max_y = max(b.y2 for b in page_bboxes)

            # 使用全宽
            crop_box = (0, min_y, page_img.width, max_y)

            cropped = page_img.crop(crop_box)
            images.append(cropped.copy())

    if not images:
        return None

    if len(images) == 1:
        return images[0]

    return compose_vertical(images)


def crop_from_page_span(
    workdir: Path,
    big_question: BigQuestion,
) -> Optional[Image.Image]:
    """
    从页面范围裁剪资料分析大题（备选方案）。

    当没有精确的 bboxes 时使用。
    """
    if not big_question.page_span:
        return None

    images: List[Image.Image] = []
    sorted_pages = sorted(big_question.page_span, key=page_index)

    for page_name in sorted_pages:
        page_image_path = workdir / f"{page_name}.png"

        if not page_image_path.is_file():
            continue

        with Image.open(page_image_path) as page_img:
            # 裁剪整页（去除页眉页脚区域）
            margin_top = 100
            margin_bottom = 150
            crop_box = (0, margin_top, page_img.width, page_img.height - margin_bottom)
            cropped = page_img.crop(crop_box)
            images.append(cropped.copy())

    if not images:
        return None

    if len(images) == 1:
        return images[0]

    return compose_vertical(images)


def process_structure_to_images(
    workdir: Path,
    structure_doc: StructureDoc,
    log: Optional[Callable[[str], None]] = None,
) -> Tuple[List[str], List[str]]:
    """
    根据结构文档生成所有输出图片。

    Args:
        workdir: 工作目录
        structure_doc: 结构文档
        log: 日志回调

    Returns:
        (normal_paths, big_paths): 普通题图片路径列表和大题图片路径列表
    """
    log_fn = log or (lambda m: None)
    output_dir = get_all_questions_dir(workdir)

    normal_paths: List[str] = []
    big_paths: List[str] = []

    # 获取资料分析的题号集合
    da_qnos = structure_doc.get_data_analysis_qnos()

    # 构建题目查找字典
    all_questions: Dict[str, QuestionNode] = {
        q.id: q for q in structure_doc.questions
    }

    # 1. 处理普通题目
    normal_questions = [
        q for q in structure_doc.questions
        if q.kind == "normal" and q.qno not in da_qnos
    ]

    log_fn(f"处理 {len(normal_questions)} 道普通题目...")

    for q in normal_questions:
        if q.qno is None:
            continue

        img = crop_question_image(workdir, q)
        if img is None:
            log_fn(f"  警告: 无法裁剪 q{q.qno}")
            continue

        out_path = output_dir / f"q{q.qno}.png"
        img.save(out_path)
        normal_paths.append(str(out_path))

    # 2. 处理资料分析大题
    log_fn(f"处理 {len(structure_doc.big_questions)} 个资料分析大题...")

    for big_q in structure_doc.big_questions:
        img = crop_big_question_image(workdir, big_q, all_questions)
        if img is None:
            log_fn(f"  警告: 无法裁剪 {big_q.id}")
            continue

        out_path = output_dir / f"{big_q.id}.png"
        img.save(out_path)
        big_paths.append(str(out_path))

    return normal_paths, big_paths


def is_crop_complete(workdir: Path, structure_doc: StructureDoc) -> bool:
    """
    检查裁剪是否完成。

    通过检查 all_questions/ 目录中的文件数量判断。
    """
    output_dir = workdir / "all_questions"
    if not output_dir.exists():
        return False

    # 获取资料分析的题号
    da_qnos = structure_doc.get_data_analysis_qnos()

    # 期望的普通题数量
    expected_normal = len([
        q for q in structure_doc.questions
        if q.kind == "normal" and q.qno not in da_qnos and q.qno is not None
    ])

    # 期望的大题数量
    expected_big = len(structure_doc.big_questions)

    # 检查文件
    normal_files = list(output_dir.glob("q*.png"))
    big_files = list(output_dir.glob("data_analysis_*.png"))

    return len(normal_files) >= expected_normal and len(big_files) >= expected_big
