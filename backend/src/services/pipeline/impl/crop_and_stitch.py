"""
crop_and_stitch.py - 裁剪拼接核心逻辑

根据 structure.json 裁剪题目图片，生成最终的输出图片。
支持图片缓存和并行裁剪以提升性能。
"""

from __future__ import annotations

import os
import shutil
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from threading import Lock
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


class PageImageCache:
    """
    页面图片缓存，避免重复打开同一页面图片。
    使用单槽缓存策略，适合按页面顺序处理的场景。
    """

    def __init__(self, workdir: Path, max_cache: int = 3):
        self._workdir = workdir
        self._max_cache = max_cache
        self._cache: Dict[str, Image.Image] = {}
        self._access_order: List[str] = []
        self._lock = Lock()

    def get(self, page_name: str) -> Optional[Image.Image]:
        """获取页面图片，优先从缓存读取。"""
        with self._lock:
            if page_name in self._cache:
                self._access_order.remove(page_name)
                self._access_order.append(page_name)
                return self._cache[page_name]

            page_path = self._workdir / f"{page_name}.png"
            if not page_path.is_file():
                return None

            img = Image.open(page_path)
            img.load()

            if len(self._cache) >= self._max_cache:
                oldest = self._access_order.pop(0)
                old_img = self._cache.pop(oldest, None)
                if old_img:
                    old_img.close()

            self._cache[page_name] = img
            self._access_order.append(page_name)
            return img

    def close(self):
        """关闭所有缓存的图片。"""
        with self._lock:
            for img in self._cache.values():
                img.close()
            self._cache.clear()
            self._access_order.clear()


def get_all_questions_dir(workdir: Path) -> Path:
    """获取最终输出目录。"""
    output_dir = workdir / "all_questions"
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


def crop_question_image(
    workdir: Path,
    question: QuestionNode,
    cache: Optional[PageImageCache] = None,
) -> Optional[Image.Image]:
    """
    裁剪单道题目的图片。

    如果题目跨多页，则垂直拼接。
    """
    if not question.bboxes:
        return None

    images: List[Image.Image] = []

    page_to_bboxes: Dict[str, List[BBox]] = {}
    for bbox in question.bboxes:
        page_to_bboxes.setdefault(bbox.page, []).append(bbox)

    sorted_pages = sorted(page_to_bboxes.keys(), key=page_index)

    for page_name in sorted_pages:
        page_bboxes = page_to_bboxes[page_name]

        if cache:
            page_img = cache.get(page_name)
            if page_img is None:
                continue
            min_y = min(b.y1 for b in page_bboxes)
            max_y = max(b.y2 for b in page_bboxes)
            crop_box = (0, min_y, page_img.width, max_y)
            cropped = page_img.crop(crop_box)
            images.append(cropped.copy())
        else:
            page_image_path = workdir / f"{page_name}.png"
            if not page_image_path.is_file():
                continue
            with Image.open(page_image_path) as page_img:
                min_y = min(b.y1 for b in page_bboxes)
                max_y = max(b.y2 for b in page_bboxes)
                crop_box = (0, min_y, page_img.width, max_y)
                cropped = page_img.crop(crop_box)
                images.append(cropped.copy())

    if not images:
        return None

    if len(images) == 1:
        return images[0]

    return compose_vertical(images)


def crop_big_question_image(
    workdir: Path,
    big_question: BigQuestion,
    all_questions: Dict[str, QuestionNode],
    cache: Optional[PageImageCache] = None,
) -> Optional[Image.Image]:
    """
    裁剪资料分析大题的图片。

    包含材料区域和所有子题，垂直拼接。
    """
    images: List[Image.Image] = []

    all_bboxes: List[Tuple[str, int, BBox]] = []

    for bbox in big_question.material_bboxes:
        all_bboxes.append((bbox.page, bbox.y1, bbox))

    for sub_id in big_question.sub_question_ids:
        sub_q = all_questions.get(sub_id)
        if sub_q:
            for bbox in sub_q.bboxes:
                all_bboxes.append((bbox.page, bbox.y1, bbox))

    if not all_bboxes:
        return crop_from_page_span(workdir, big_question, cache)

    all_bboxes.sort(key=lambda x: (page_index(x[0]), x[1]))

    page_to_bboxes: Dict[str, List[BBox]] = {}
    for page_name, _, bbox in all_bboxes:
        page_to_bboxes.setdefault(page_name, []).append(bbox)

    sorted_pages = sorted(page_to_bboxes.keys(), key=page_index)

    for page_name in sorted_pages:
        page_bboxes = page_to_bboxes[page_name]

        if cache:
            page_img = cache.get(page_name)
            if page_img is None:
                continue
            min_y = min(b.y1 for b in page_bboxes)
            max_y = max(b.y2 for b in page_bboxes)
            crop_box = (0, min_y, page_img.width, max_y)
            cropped = page_img.crop(crop_box)
            images.append(cropped.copy())
        else:
            page_image_path = workdir / f"{page_name}.png"
            if not page_image_path.is_file():
                continue
            with Image.open(page_image_path) as page_img:
                min_y = min(b.y1 for b in page_bboxes)
                max_y = max(b.y2 for b in page_bboxes)
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
    cache: Optional[PageImageCache] = None,
) -> Optional[Image.Image]:
    """
    从页面范围裁剪资料分析大题（备选方案）。

    当没有精确的 bboxes 时使用。
    """
    if not big_question.page_span:
        return None

    images: List[Image.Image] = []
    sorted_pages = sorted(big_question.page_span, key=page_index)
    margin_top = 100
    margin_bottom = 150

    for page_name in sorted_pages:
        if cache:
            page_img = cache.get(page_name)
            if page_img is None:
                continue
            crop_box = (0, margin_top, page_img.width, page_img.height - margin_bottom)
            cropped = page_img.crop(crop_box)
            images.append(cropped.copy())
        else:
            page_image_path = workdir / f"{page_name}.png"
            if not page_image_path.is_file():
                continue
            with Image.open(page_image_path) as page_img:
                crop_box = (0, margin_top, page_img.width, page_img.height - margin_bottom)
                cropped = page_img.crop(crop_box)
                images.append(cropped.copy())

    if not images:
        return None

    if len(images) == 1:
        return images[0]

    return compose_vertical(images)


def _crop_and_save_normal(
    args: Tuple[Path, QuestionNode, Path, PageImageCache]
) -> Optional[str]:
    """Worker function for parallel normal question cropping."""
    workdir, q, output_dir, cache = args
    if q.qno is None:
        return None
    img = crop_question_image(workdir, q, cache)
    if img is None:
        return None
    out_path = output_dir / f"q{q.qno}.png"
    img.save(out_path)
    img.close()
    return str(out_path)


def _crop_and_save_big(
    args: Tuple[Path, BigQuestion, Dict[str, QuestionNode], Path, PageImageCache]
) -> Optional[str]:
    """Worker function for parallel big question cropping."""
    workdir, big_q, all_questions, output_dir, cache = args
    img = crop_big_question_image(workdir, big_q, all_questions, cache)
    if img is None:
        return None
    out_path = output_dir / f"{big_q.id}.png"
    img.save(out_path)
    img.close()
    return str(out_path)


def process_structure_to_images(
    workdir: Path,
    structure_doc: StructureDoc,
    log: Optional[Callable[[str], None]] = None,
    max_workers: int = 0,
) -> Tuple[List[str], List[str]]:
    """
    根据结构文档生成所有输出图片。

    Args:
        workdir: 工作目录
        structure_doc: 结构文档
        log: 日志回调
        max_workers: 并行worker数量，0表示自动

    Returns:
        (normal_paths, big_paths): 普通题图片路径列表和大题图片路径列表
    """
    log_fn = log or (lambda m: None)
    output_dir = get_all_questions_dir(workdir)

    da_qnos = structure_doc.get_data_analysis_qnos()
    all_questions: Dict[str, QuestionNode] = {
        q.id: q for q in structure_doc.questions
    }

    normal_questions = [
        q for q in structure_doc.questions
        if q.kind == "normal" and q.qno not in da_qnos and q.qno is not None
    ]

    cache = PageImageCache(workdir, max_cache=5)

    try:
        normal_paths: List[str] = []
        big_paths: List[str] = []

        workers = max_workers if max_workers > 0 else min(os.cpu_count() or 4, 6)
        total_tasks = len(normal_questions) + len(structure_doc.big_questions)

        if total_tasks > 10 and workers > 1:
            log_fn(f"并行处理 {len(normal_questions)} 道普通题 + {len(structure_doc.big_questions)} 个大题 (workers={workers})")

            with ThreadPoolExecutor(max_workers=workers) as executor:
                normal_futures = [
                    executor.submit(_crop_and_save_normal, (workdir, q, output_dir, cache))
                    for q in normal_questions
                ]
                for future in as_completed(normal_futures):
                    result = future.result()
                    if result:
                        normal_paths.append(result)

                big_futures = [
                    executor.submit(_crop_and_save_big, (workdir, big_q, all_questions, output_dir, cache))
                    for big_q in structure_doc.big_questions
                ]
                for future in as_completed(big_futures):
                    result = future.result()
                    if result:
                        big_paths.append(result)
        else:
            log_fn(f"处理 {len(normal_questions)} 道普通题目...")
            for q in normal_questions:
                img = crop_question_image(workdir, q, cache)
                if img is None:
                    log_fn(f"  警告: 无法裁剪 q{q.qno}")
                    continue
                out_path = output_dir / f"q{q.qno}.png"
                img.save(out_path)
                img.close()
                normal_paths.append(str(out_path))

            log_fn(f"处理 {len(structure_doc.big_questions)} 个资料分析大题...")
            for big_q in structure_doc.big_questions:
                img = crop_big_question_image(workdir, big_q, all_questions, cache)
                if img is None:
                    log_fn(f"  警告: 无法裁剪 {big_q.id}")
                    continue
                out_path = output_dir / f"{big_q.id}.png"
                img.save(out_path)
                img.close()
                big_paths.append(str(out_path))

        return normal_paths, big_paths
    finally:
        cache.close()


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
