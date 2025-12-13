"""
ocr_cache.py - OCR 结果缓存模块

提供 PP-StructureV3 OCR 结果的持久化缓存，避免重复调用 OCR。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ....common import layout_blocks_from_doc


def get_ocr_cache_dir(workdir: Path) -> Path:
    """获取 OCR 缓存目录。"""
    cache_dir = workdir / "ocr"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir


def get_ocr_cache_path(workdir: Path, page_name: str) -> Path:
    """获取单页 OCR 缓存文件路径。"""
    cache_dir = get_ocr_cache_dir(workdir)
    return cache_dir / f"{page_name}.json"


def has_ocr_cache(workdir: Path, page_name: str) -> bool:
    """检查是否存在 OCR 缓存。"""
    cache_path = get_ocr_cache_path(workdir, page_name)
    return cache_path.is_file()


def load_ocr_cache(workdir: Path, page_name: str) -> Optional[Dict[str, Any]]:
    """
    加载 OCR 缓存。

    Returns:
        缓存的 OCR 结果，如果不存在返回 None
    """
    cache_path = get_ocr_cache_path(workdir, page_name)
    if not cache_path.is_file():
        return None

    with cache_path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_ocr_cache(
    workdir: Path,
    page_name: str,
    blocks: List[Dict[str, Any]],
    image_size: Tuple[int, int],
) -> Path:
    """
    保存 OCR 结果到缓存。

    Args:
        workdir: 工作目录
        page_name: 页面名称 (如 "page_1")
        blocks: PP-StructureV3 提取的版面块列表
        image_size: 图片尺寸 (width, height)

    Returns:
        缓存文件路径
    """
    cache_path = get_ocr_cache_path(workdir, page_name)

    cache_data = {
        "page_name": page_name,
        "image_width": image_size[0],
        "image_height": image_size[1],
        "blocks": blocks,
    }

    with cache_path.open("w", encoding="utf-8") as f:
        json.dump(cache_data, f, ensure_ascii=False, indent=2)

    return cache_path


def run_ocr_with_cache(
    pipeline: Any,
    page_image_path: Path,
    workdir: Path,
    force: bool = False,
) -> Tuple[List[Dict[str, Any]], Tuple[int, int]]:
    """
    运行 OCR 并缓存结果，如果已有缓存则直接返回。

    Args:
        pipeline: PP-StructureV3 pipeline 实例
        page_image_path: 页面图片路径
        workdir: 工作目录
        force: 是否强制重新运行 OCR

    Returns:
        (blocks, image_size): 版面块列表和图片尺寸
    """
    from PIL import Image

    page_name = page_image_path.stem

    # 检查缓存
    if not force:
        cached = load_ocr_cache(workdir, page_name)
        if cached is not None:
            blocks = cached.get("blocks", [])
            image_size = (cached.get("image_width", 0), cached.get("image_height", 0))
            return blocks, image_size

    # 运行 OCR
    doc = pipeline.predict(str(page_image_path))[0]
    blocks = layout_blocks_from_doc(doc)

    # 获取图片尺寸
    with Image.open(page_image_path) as img:
        image_size = (img.width, img.height)

    # 保存缓存
    save_ocr_cache(workdir, page_name, blocks, image_size)

    return blocks, image_size


def load_all_ocr_caches(workdir: Path) -> Dict[str, Dict[str, Any]]:
    """
    加载所有 OCR 缓存。

    Returns:
        {page_name: cache_data} 字典
    """
    cache_dir = get_ocr_cache_dir(workdir)
    caches = {}

    for cache_file in cache_dir.glob("page_*.json"):
        page_name = cache_file.stem
        with cache_file.open("r", encoding="utf-8") as f:
            caches[page_name] = json.load(f)

    return caches


def is_ocr_complete(workdir: Path) -> bool:
    """
    检查所有页面的 OCR 是否完成。

    通过比较 page_*.png 文件和 ocr/page_*.json 文件数量判断。
    """
    page_images = list(workdir.glob("page_*.png"))
    if not page_images:
        return False

    cache_dir = get_ocr_cache_dir(workdir)
    cache_files = list(cache_dir.glob("page_*.json"))

    # 检查每个 page_*.png 是否有对应的缓存
    page_names = {p.stem for p in page_images}
    cached_names = {c.stem for c in cache_files}

    return page_names == cached_names
