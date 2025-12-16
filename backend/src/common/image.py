"""
image.py - 图片处理工具

提供图片裁剪、拼接等工具函数
"""

from pathlib import Path
from typing import Optional
from PIL import Image


def union_boxes(
    boxes: list[list[int]] | list[tuple[int, int, int, int]]
) -> Optional[tuple[int, int, int, int]]:
    """
    计算多个 bbox 的并集（最小外接矩形）。

    Args:
        boxes: bbox 列表，每个 bbox 为 [x1, y1, x2, y2]

    Returns:
        并集 bbox (x1, y1, x2, y2)，空列表返回 None
    """
    xs: list[int] = []
    ys: list[int] = []
    for b in boxes:
        if len(b) >= 4:
            xs.extend([int(b[0]), int(b[2])])
            ys.extend([int(b[1]), int(b[3])])
    if not xs:
        return None
    return (min(xs), min(ys), max(xs), max(ys))


def crop_and_save(
    img_path: Path,
    box: tuple[int, int, int, int],
    output_path: Path,
) -> tuple[int, int, int, int]:
    """
    裁剪图片并保存。

    Args:
        img_path: 原图路径
        box: 裁剪框 (x1, y1, x2, y2)
        output_path: 输出路径

    Returns:
        实际使用的裁剪框（经过边界修正）
    """
    with Image.open(img_path) as img:
        x1, y1, x2, y2 = box

        x1 = max(0, min(x1, img.width))
        x2 = max(0, min(x2, img.width))
        y1 = max(0, min(y1, img.height))
        y2 = max(0, min(y2, img.height))

        if x2 <= x1:
            x1, x2 = 0, img.width
        if y2 <= y1:
            y1, y2 = 0, img.height

        final_box = (x1, y1, x2, y2)
        crop_img = img.crop(final_box)

        output_path.parent.mkdir(parents=True, exist_ok=True)
        crop_img.save(output_path)
        crop_img.close()

    return final_box


def crop_page_and_save(
    img_dir: Path, page: str, box: tuple[int, int, int, int], name: str
) -> tuple[str, tuple[int, int, int, int]]:
    """
    按页面名裁剪并保存图片，返回相对路径和实际裁剪框。

    Args:
        img_dir: 试卷目录（包含 page_X.png）
        page: 页面名，如 "page_6"
        box: (x1, y1, x2, y2)
        name: 输出文件名，如 "big_1.png"

    Returns:
        (相对路径字符串, 实际裁剪框)

    Raises:
        FileNotFoundError: 页面图片不存在时抛出
    """
    img_path = img_dir / f"{page}.png"
    if not img_path.is_file():
        raise FileNotFoundError(img_path)

    with Image.open(img_path) as img:
        x1, y1, x2, y2 = box
        x1 = max(0, min(x1, img.width))
        x2 = max(0, min(x2, img.width))
        y1 = max(0, min(y1, img.height))
        y2 = max(0, min(y2, img.height))
        if x2 <= x1:
            x1, x2 = 0, img.width
        if y2 <= y1:
            y1, y2 = 0, img.height
        final_box = (x1, y1, x2, y2)
        crop = img.crop(final_box)

        out_dir = img_dir / f"questions_{page}"
        out_dir.mkdir(parents=True, exist_ok=True)

        out_path = out_dir / name
        crop.save(out_path)
        crop.close()

    try:
        rel_path = out_path.relative_to(img_dir.parent)
    except ValueError:
        rel_path = out_path

    return str(rel_path), final_box


def compose_vertical(images: list[Image.Image]) -> Image.Image:
    """
    将多张图片按顺序竖直拼接成一张长图。

    Args:
        images: PIL Image 对象列表

    Returns:
        拼接后的长图

    Raises:
        ValueError: 图片列表为空时抛出
    """
    if not images:
        raise ValueError("no images to compose")

    widths = [im.width for im in images]
    heights = [im.height for im in images]

    max_width = max(widths)
    total_height = sum(heights)

    mode = images[0].mode
    if mode == "P":
        mode = "RGBA"
        images = [im.convert(mode) for im in images]

    bg_color = (255, 255, 255, 0) if "A" in mode else (255, 255, 255)
    long_img = Image.new(mode, (max_width, total_height), bg_color)

    y_offset = 0
    for im in images:
        long_img.paste(im, (0, y_offset))
        y_offset += im.height

    return long_img


def compute_smart_crop_box(
    blocks: list[dict[str, any]],
    page_size: tuple[int, int],
    footer_top: Optional[int] = None,
    use_full_width: bool = True,
    margin_ratio: float = 0.008,
    min_margin: int = 3,
    max_margin: int = 15,
) -> tuple[int, int, int, int]:
    """
    智能计算裁剪框。

    改进点：
    1. margin 基于页面尺寸动态计算
    2. 自动排除 header/footer/number 块
    3. 考虑 footer 位置避免截入页脚

    Args:
        blocks: 属于该题目的版面块列表
        page_size: (width, height) 页面尺寸
        footer_top: 页脚顶部 y 坐标（可选）
        use_full_width: 是否使用全页宽度（默认 True）
        margin_ratio: margin 占页面尺寸的比例
        min_margin: 最小 margin 像素
        max_margin: 最大 margin 像素

    Returns:
        裁剪框 (left, top, right, bottom)
    """
    width, height = page_size

    # 动态计算 margin
    margin_y = max(min_margin, min(max_margin, int(height * margin_ratio)))
    margin_x = max(min_margin, min(max_margin, int(width * margin_ratio)))

    # 收集有效块的坐标（排除 header/footer/number）
    xs: list[int] = []
    ys: list[int] = []
    for blk in blocks:
        label = blk.get("label", "")
        if label in {"footer", "number", "header"}:
            continue
        bbox = blk.get("bbox")
        if bbox and isinstance(bbox, (list, tuple)) and len(bbox) == 4:
            xs.extend([int(bbox[0]), int(bbox[2])])
            ys.extend([int(bbox[1]), int(bbox[3])])

    # 如果过滤后没有有效块，退回全量计算
    if not ys:
        for blk in blocks:
            bbox = blk.get("bbox")
            if bbox and isinstance(bbox, (list, tuple)) and len(bbox) == 4:
                xs.extend([int(bbox[0]), int(bbox[2])])
                ys.extend([int(bbox[1]), int(bbox[3])])

    if not ys:
        return (0, 0, width, height)

    # 计算边界
    top = max(0, min(ys) - margin_y)
    bottom = min(height, max(ys) + margin_y)

    # 考虑 footer
    if footer_top is not None:
        bottom = min(bottom, max(0, footer_top - margin_y))

    if use_full_width:
        left, right = 0, width
    else:
        left = max(0, min(xs) - margin_x)
        right = min(width, max(xs) + margin_x)

    return (left, top, right, bottom)


def find_footer_top_from_meta(meta: dict[str, any]) -> Optional[int]:
    """
    根据 meta.json 中的 other_blocks 提取页脚顶部 y 值（footer/number）。

    Args:
        meta: meta.json 字典

    Returns:
        页脚顶部y坐标，如果没有找到则返回None
    """
    ys: list[int] = []
    for q in meta.get("questions", []):
        for blk in q.get("other_blocks", []):
            if blk.get("label") in {"footer", "number"}:
                bbox = blk.get("bbox")
                if bbox and isinstance(bbox, (list, tuple)) and len(bbox) == 4:
                    ys.append(int(bbox[1]))
    return min(ys) if ys else None
