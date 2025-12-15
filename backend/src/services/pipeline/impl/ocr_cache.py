"""
ocr_cache.py - OCR 结果缓存模块

提供 PP-StructureV3 OCR 结果的持久化缓存，避免重复调用 OCR。
包含内存缓存和性能优化功能。
"""

from __future__ import annotations

import json
import os
import threading
from collections import OrderedDict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ....common import layout_blocks_from_doc
from ....common.perf import perf_enabled, perf_event, perf_span

# In-memory LRU cache for OCR results (avoid re-loading large JSON files)
_mem_lock = threading.Lock()
_mem_cache: "OrderedDict[str, Tuple[List[Dict[str, Any]], Tuple[int, int]]]" = OrderedDict()


def _mem_cache_enabled() -> bool:
    """Check if in-memory cache is enabled."""
    return (os.getenv("EXAMPAPER_OCR_MEM_CACHE", "0") or "").strip() == "1"


def _mem_cache_max_pages() -> int:
    """Get maximum pages to keep in memory cache."""
    raw = (os.getenv("EXAMPAPER_OCR_MEM_CACHE_MAX_PAGES", "") or "").strip()
    if not raw:
        return 64
    try:
        v = int(raw)
        if v <= 0:
            return 64
        return min(v, 512)
    except ValueError:
        return 64


def _mem_key(workdir: Path, page_name: str) -> str:
    """Generate memory cache key."""
    return f"{str(workdir)}::{page_name}"


def _mem_get(workdir: Path, page_name: str) -> Optional[Tuple[List[Dict[str, Any]], Tuple[int, int]]]:
    """Get from memory cache (LRU)."""
    if not _mem_cache_enabled():
        return None
    key = _mem_key(workdir, page_name)
    with _mem_lock:
        val = _mem_cache.get(key)
        if val is None:
            return None
        # Move to end (LRU)
        _mem_cache.move_to_end(key)
        return val


def _mem_put(workdir: Path, page_name: str, blocks: List[Dict[str, Any]], image_size: Tuple[int, int]) -> None:
    """Put into memory cache (LRU eviction)."""
    if not _mem_cache_enabled():
        return
    key = _mem_key(workdir, page_name)
    with _mem_lock:
        _mem_cache[key] = (blocks, image_size)
        _mem_cache.move_to_end(key)
        # Evict oldest entries if over limit
        while len(_mem_cache) > _mem_cache_max_pages():
            _mem_cache.popitem(last=False)


def _json_dump_kwargs(pretty: bool) -> Dict[str, Any]:
    """Get JSON dump kwargs based on pretty flag."""
    if pretty:
        return {"ensure_ascii": False, "indent": 2}
    return {"ensure_ascii": False, "separators": (",", ":")}


def _trim_non_text_content(blocks: List[Dict[str, Any]]) -> None:
    """
    裁剪非文本块的content以减少JSON大小。

    某些table/figure block的content可能是超长HTML/字符串，导致JSON写入巨大且慢。
    通过EXAMPAPER_TRIM_NON_TEXT_CONTENT_MAX环境变量启用（单位：字符数）。
    """
    raw = (os.getenv("EXAMPAPER_TRIM_NON_TEXT_CONTENT_MAX", "") or "").strip()
    if not raw:
        return
    try:
        max_chars = int(raw)
    except ValueError:
        return
    if max_chars <= 0:
        return

    for b in blocks:
        label = str(b.get("label") or "")
        if label == "text":
            continue
        c = b.get("content")
        if isinstance(c, str) and len(c) > max_chars:
            b["content_len"] = len(c)
            b["content_truncated"] = True
            b["content"] = c[:max_chars]


def get_ocr_cache_dir(workdir: Path) -> Path:
    """
    获取 OCR 缓存目录（确保存在）。

    注意：仅写入路径应调用此函数；只读场景请避免触发 mkdir 造成额外 I/O。
    """
    cache_dir = workdir / "ocr"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir


def _ocr_cache_dir_path(workdir: Path) -> Path:
    """OCR 缓存目录路径（不做 mkdir，用于只读场景）。"""
    return workdir / "ocr"


def get_ocr_cache_path(workdir: Path, page_name: str) -> Path:
    """获取单页 OCR 缓存文件路径（只读场景，不创建目录）。"""
    return _ocr_cache_dir_path(workdir) / f"{page_name}.json"


def has_ocr_cache(workdir: Path, page_name: str) -> bool:
    """检查是否存在 OCR 缓存（只读操作，不创建目录）。"""
    cache_path = _ocr_cache_dir_path(workdir) / f"{page_name}.json"
    return cache_path.is_file()


def load_ocr_cache(workdir: Path, page_name: str) -> Optional[Dict[str, Any]]:
    """
    加载 OCR 缓存（只读操作，不创建目录）。

    Returns:
        缓存的 OCR 结果，如果不存在返回 None
    """
    cache_path = _ocr_cache_dir_path(workdir) / f"{page_name}.json"
    if not cache_path.is_file():
        return None

    with cache_path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_ocr_cache(
    workdir: Path,
    page_name: str,
    blocks: List[Dict[str, Any]],
    image_size: Tuple[int, int],
    pretty: bool = False,
) -> Path:
    """
    保存 OCR 结果到缓存（写入操作，会创建目录）。

    Args:
        workdir: 工作目录
        page_name: 页面名称 (如 "page_1")
        blocks: PP-StructureV3 提取的版面块列表
        image_size: 图片尺寸 (width, height)
        pretty: 是否使用pretty格式（默认False，使用紧凑格式）

    Returns:
        缓存文件路径
    """
    cache_dir = get_ocr_cache_dir(workdir)  # 确保目录存在
    cache_path = cache_dir / f"{page_name}.json"

    cache_data = {
        "page_name": page_name,
        "image_width": image_size[0],
        "image_height": image_size[1],
        "blocks": blocks,
    }

    with cache_path.open("w", encoding="utf-8") as f:
        json.dump(cache_data, f, **_json_dump_kwargs(pretty))

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
    input_bytes = None
    try:
        input_bytes = page_image_path.stat().st_size
    except OSError:
        pass

    # Check in-memory cache first (fastest)
    mem = _mem_get(workdir, page_name)
    if mem is not None and not force:
        blocks, image_size = mem
        if perf_enabled():
            perf_event(
                "ocr.cache.mem_hit",
                page=page_name,
                blocks=len(blocks),
                image_w=image_size[0],
                image_h=image_size[1],
                input_bytes=input_bytes,
            )
        return blocks, image_size

    # Check disk cache
    if not force:
        with perf_span("ocr.cache.load", page=page_name, input_bytes=input_bytes):
            cached = load_ocr_cache(workdir, page_name)
        if cached is not None:
            blocks = cached.get("blocks", [])
            image_size = (cached.get("image_width", 0), cached.get("image_height", 0))
            # Update memory cache
            _mem_put(workdir, page_name, blocks, image_size)
            if perf_enabled():
                perf_event(
                    "ocr.cache.hit",
                    page=page_name,
                    blocks=len(blocks),
                    image_w=image_size[0],
                    image_h=image_size[1],
                    input_bytes=input_bytes,
                )
            return blocks, image_size

    # Cache miss: run OCR
    # Pre-load image size and optionally decode to array (move I/O out of GPU lock)
    image_size = (0, 0)
    img_input: Any = str(page_image_path)

    with perf_span("ocr.image.open", page=page_name, input_bytes=input_bytes):
        with Image.open(page_image_path) as img:
            image_size = (img.width, img.height)
            # Optional: pass ndarray to predict() to avoid I/O inside GPU lock
            if (os.getenv("EXAMPAPER_OCR_PASS_IMAGE", "0") or "").strip() == "1":
                try:
                    import numpy as np  # type: ignore
                    img.load()
                    img_input = np.array(img)
                except Exception:
                    # Fallback to path if numpy not available or conversion fails
                    img_input = str(page_image_path)

    # Run OCR (this will acquire GPU lock inside _GpuLockedPipeline.predict)
    with perf_span("ocr.predict.total", page=page_name, input_bytes=input_bytes, image_w=image_size[0], image_h=image_size[1]):
        try:
            doc = pipeline.predict(img_input)[0]
        except Exception as e:
            # Compatibility guard: some PPStructureV3 builds only accept path/bytes input
            if not isinstance(img_input, str):
                if perf_enabled():
                    perf_event(
                        "ocr.predict.fallback_to_path",
                        page=page_name,
                        error=f"{type(e).__name__}: {e}",
                    )
                doc = pipeline.predict(str(page_image_path))[0]
            else:
                raise

    with perf_span("ocr.blocks.normalize", page=page_name):
        blocks = layout_blocks_from_doc(doc)
        _trim_non_text_content(blocks)

    # Save cache
    pretty = (os.getenv("EXAMPAPER_OCR_CACHE_PRETTY", "0") or "").strip() == "1"
    with perf_span("ocr.cache.save", page=page_name, blocks=len(blocks), pretty=pretty):
        cache_path = get_ocr_cache_path(workdir, page_name)
        cache_data = {
            "page_name": page_name,
            "image_width": image_size[0],
            "image_height": image_size[1],
            "blocks": blocks,
        }
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        with cache_path.open("w", encoding="utf-8") as f:
            json.dump(cache_data, f, **_json_dump_kwargs(pretty))

    try:
        written = cache_path.stat().st_size
    except OSError:
        written = None

    if perf_enabled():
        perf_event(
            "ocr.cache.saved",
            page=page_name,
            blocks=len(blocks),
            bytes_written=written,
            pretty=pretty,
        )

    # Update memory cache
    _mem_put(workdir, page_name, blocks, image_size)

    return blocks, image_size


def load_all_ocr_caches(workdir: Path) -> Dict[str, Dict[str, Any]]:
    """
    加载所有 OCR 缓存。

    Returns:
        {page_name: cache_data} 字典
    """
    cache_dir = _ocr_cache_dir_path(workdir)
    if not cache_dir.is_dir():
        return {}

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

    cache_dir = _ocr_cache_dir_path(workdir)
    if not cache_dir.is_dir():
        return False

    cache_files = list(cache_dir.glob("page_*.json"))

    # 检查每个 page_*.png 是否有对应的缓存
    page_names = {p.stem for p in page_images}
    cached_names = {c.stem for c in cache_files}

    return page_names == cached_names
