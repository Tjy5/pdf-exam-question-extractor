"""
compose_long_image.py - 长图拼接核心逻辑

将跨页题目片段拼接成单张长图。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Tuple

from PIL import Image

from ....common import (
    load_meta,
    save_meta,
    resolve_image_path,
    compose_vertical,
)


def process_meta_file(
    meta_path: Path, workdir: Path
) -> Tuple[List[str], List[str]]:
    """
    处理单个 meta.json 文件，生成长图。

    Args:
        meta_path: meta.json 文件路径
        workdir: 试卷工作目录

    Returns:
        (composed_qnos, long_paths): 已拼接的题号列表和长图路径列表
    """
    meta = load_meta(meta_path)
    changed = False
    out_dir = meta_path.parent

    composed_qnos: List[str] = []
    long_paths: List[str] = []

    # 1) 小题长图（基于 questions[*].segments）
    questions: List[Dict[str, Any]] = meta.get("questions") or []
    for q in questions:
        segments = q.get("segments") or []
        if not segments:
            continue

        # 检查是否已存在
        long_image_path_str = q.get("long_image")
        if long_image_path_str:
            existing = resolve_image_path(long_image_path_str, workdir)
            if existing.is_file():
                continue

        img_paths: List[Path] = []
        for seg in segments:
            img_str = seg.get("image")
            if not img_str:
                continue
            img_path = resolve_image_path(img_str, workdir)
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
            rel_path = out_path.relative_to(workdir.parent)
        except ValueError:
            rel_path = out_path

        q["long_image"] = str(rel_path)
        composed_qnos.append(f"q{qno}")
        long_paths.append(str(out_path))
        changed = True

    # 2) 资料分析大题长图（基于 big_questions[*].segments）
    big_questions: List[Dict[str, Any]] = meta.get("big_questions") or []
    for bq in big_questions:
        segments = bq.get("segments") or []
        if not segments:
            continue

        # 检查是否已存在
        combined_path_str = bq.get("combined_image")
        if combined_path_str:
            existing = resolve_image_path(combined_path_str, workdir)
            if existing.is_file():
                continue

        img_paths: List[Path] = []
        for seg in segments:
            img_str = seg.get("image")
            if not img_str:
                continue
            img_path = resolve_image_path(img_str, workdir)
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
            rel_path = out_path.relative_to(workdir.parent)
        except ValueError:
            rel_path = out_path

        bq["combined_image"] = str(rel_path)
        composed_qnos.append(bq_id)
        long_paths.append(str(out_path))
        changed = True

    if changed:
        save_meta(meta_path, meta)

    return composed_qnos, long_paths
