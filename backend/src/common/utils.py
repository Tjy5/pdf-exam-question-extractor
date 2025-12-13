"""
utils.py - 通用工具函数

提供版面分析、section boundary检测等工具函数
"""

from typing import Any, Optional
from .types import (
    QUESTION_HEAD_PATTERN,
    SECTION_TITLE_PATTERN,
    SECTION_PART_PATTERN,
    SECTION_HEAD_KEYWORDS,
    SECTION_INTRO_KEYWORDS,
    DATA_INTRO_KEYWORDS,
    QUESTION_RANGE_PATTERN,
)


def is_section_boundary_block(blk: dict[str, Any]) -> bool:
    """
    判断某个版面块是否是"部分标题/说明"，如 "一、常识判断"。

    这类块不应归入任何一道小题中。

    Args:
        blk: 版面块字典

    Returns:
        是否为 section boundary
    """
    label = blk.get("label") or ""
    if label in {"footer", "number", "header"}:
        return False

    content = blk.get("content") or ""
    if not isinstance(content, str):
        content = str(content)
    text = content.strip()
    if not text:
        return False

    # 显式的大题标题，如 "一、常识判断"
    if SECTION_TITLE_PATTERN.search(text):
        return True

    # "第X部分" 这一类提示
    if SECTION_PART_PATTERN.search(text):
        return True

    # 带有部分说明的句子，如 "数量关系：本部分包括……"
    if any(k in text for k in SECTION_HEAD_KEYWORDS) and any(
        k in text for k in SECTION_INTRO_KEYWORDS
    ):
        return True

    # 资料分析/材料类的开篇提示
    if any(k in text for k in DATA_INTRO_KEYWORDS):
        return True

    # "回答XX-XX题" 范围提示
    if QUESTION_RANGE_PATTERN.search(text):
        return True

    return False


def detect_section_boundaries(blocks: list[dict[str, Any]]) -> set[int]:
    """
    返回当前页中所有 "部分标题/说明" 所在的索引集合。

    Args:
        blocks: 版面块列表

    Returns:
        boundary 索引集合
    """
    boundary_indices: set[int] = set()
    for idx, blk in enumerate(blocks):
        if is_section_boundary_block(blk):
            boundary_indices.add(idx)
    return boundary_indices


def detect_continuation_blocks(
    blocks: list[dict[str, Any]],
    section_boundaries: Optional[set[int]] = None,
    prev_question_context: Optional[dict[str, Any]] = None,
) -> tuple[list[dict[str, Any]], float]:
    """
    检测当前页顶部的"上一题续接内容"。

    在当前页的版面块中，找到"出现在第一个题号之前的正文块"，
    作为上一题跨页续接内容的候选。

    改进点：
    1. 增加置信度评估
    2. 更严格的 section boundary 检测
    3. 支持传入上一题上下文（预留扩展）

    Args:
        blocks: 当前页的版面块列表
        section_boundaries: section boundary 索引集合
        prev_question_context: 上一题的上下文信息（可选，预留扩展）

    Returns:
        (续接块列表, 置信度 0.0-1.0)
    """
    boundary_set: set[int] = section_boundaries or set()

    # 找到第一个新题号所在位置
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

    # 确定截止位置：题号或 section boundary，取较小者
    stop_idx = len(blocks)
    if first_head_idx is not None:
        stop_idx = first_head_idx
    if boundary_set:
        before_stop = [b for b in boundary_set if b < stop_idx]
        if before_stop:
            stop_idx = min(before_stop)

    # 收集候选续接块
    candidates: list[dict[str, Any]] = []
    for idx, blk in enumerate(blocks):
        if idx >= stop_idx:
            break
        label = blk.get("label", "")
        bbox = blk.get("bbox")
        if (
            label in {"footer", "number", "header"}
            or not isinstance(bbox, (list, tuple))
            or len(bbox) != 4
        ):
            continue
        # 跳过 section boundary
        if idx in boundary_set or is_section_boundary_block(blk):
            continue
        candidates.append(blk)

    # 计算置信度
    confidence = 1.0
    if not candidates:
        confidence = 0.0
    elif stop_idx == 0:
        # 页面开头就是题号，无续接
        confidence = 0.0
    else:
        # 基于候选块数量的简单置信度估算（再叠加内容/位置惩罚）
        if len(candidates) <= 2:
            confidence = 0.9
        elif len(candidates) <= 5:
            confidence = 0.7
        else:
            confidence = 0.5

        # 内容过滤：答题卡/二维码/扫码答案等不应作为上一题续接
        bad_keywords = ("答案", "扫码", "二维码", "答题卡")
        all_text = "".join(str(blk.get("content") or "") for blk in candidates)
        if any(k in all_text for k in bad_keywords):
            confidence = 0.0

        # 位置惩罚：续接内容应出现在页顶；若候选块整体落在页面下半区，则显著降低置信度
        if confidence > 0.0:
            # 无 page_size 信息时，用当前页所有 bbox 的最大 y2 近似页面高度
            page_bottom = 0.0
            for blk in blocks:
                bbox = blk.get("bbox")
                if isinstance(bbox, (list, tuple)) and len(bbox) == 4:
                    try:
                        page_bottom = max(page_bottom, float(bbox[3]))
                    except (TypeError, ValueError):
                        continue

            cand_tops: list[float] = []
            for blk in candidates:
                bbox = blk.get("bbox")
                if isinstance(bbox, (list, tuple)) and len(bbox) == 4:
                    try:
                        cand_tops.append(float(bbox[1]))
                    except (TypeError, ValueError):
                        continue

            if page_bottom > 0 and cand_tops and min(cand_tops) >= page_bottom * 0.5:
                confidence *= 0.2

    return candidates, confidence
