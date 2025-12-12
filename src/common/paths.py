"""
paths.py - 路径解析和管理工具

提供项目中的路径相关工具函数
"""

from pathlib import Path
from typing import Optional
from .types import DEFAULT_DATA_DIR, LEGACY_PDF_IMAGES_DIR


def page_index(page_name: str) -> int:
    """
    提取 page_6, page_10 里的数字部分，用于排序。

    Args:
        page_name: 页面名称，如 "page_6" 或 "page_10"

    Returns:
        页面数字索引，解析失败返回 0
    """
    try:
        return int(page_name.split("_")[-1])
    except Exception:
        return 0


def resolve_image_path(img_path_str: str, base_dir: Path) -> Path:
    """
    解析 meta.json 中存储的相对图片路径为可用的绝对路径。

    支持以下情况：
    1. 绝对路径直接存在
    2. 相对于 base_dir 的路径
    3. 相对于 base_dir.parent 的路径
    4. 目录名变更后的路径（提取子目录+文件名在 base_dir 中查找）

    Args:
        img_path_str: meta.json 中的图片路径字符串
        base_dir: 基准目录（通常是 img_dir 或 img_dir.parent）

    Returns:
        解析后的 Path 对象
    """
    # 规范化路径分隔符以支持跨平台
    norm_str = img_path_str.replace("\\", "/")
    p = Path(norm_str)

    if p.is_file():
        return p
    candidate = (base_dir / norm_str).resolve()
    if candidate.is_file():
        return candidate
    candidate2 = (base_dir.parent / norm_str).resolve()
    if candidate2.is_file():
        return candidate2

    # 处理目录名变更的情况：提取 questions_page_X/filename 部分
    # 路径格式可能是: old_dir_name/questions_page_X/q123.png
    # 从后往前找 questions_page_ 以处理嵌套情况
    parts = p.parts
    idx = next(
        (i for i in range(len(parts) - 1, -1, -1)
         if parts[i].startswith("questions_page_")),
        None
    )
    if idx is not None:
        rel_parts = parts[idx:]
        candidate3 = base_dir.joinpath(*rel_parts).resolve()
        if candidate3.is_file():
            return candidate3

    # 最后尝试只用文件名在 base_dir 及子目录中查找
    filename = p.name
    for subdir in base_dir.glob("questions_page_*"):
        candidate4 = subdir / filename
        if candidate4.is_file():
            return candidate4

    return candidate2


def get_meta_path(img_dir: Path, page_name: str) -> Path:
    """
    获取指定页面的 meta.json 路径。

    Args:
        img_dir: 图片目录（如 pdf_images/试卷名/）
        page_name: 页面名称（如 "page_6"）

    Returns:
        meta.json 的完整路径
    """
    return img_dir / f"questions_{page_name}" / "meta.json"


def iter_meta_paths(img_dir: Path) -> list[Path]:
    """
    遍历指定目录下的 questions_page_*/meta.json，并按页码排序。

    Args:
        img_dir: 试卷目录，如 pdf_images/xxx

    Returns:
        排好序的 meta.json 路径列表
    """
    metas = list(img_dir.glob("questions_page_*/meta.json"))
    metas.sort(
        key=lambda p: page_index(
            p.parent.name.replace("questions_", "").replace("page_", "")
        )
    )
    return metas


def auto_latest_exam_dir(base_dir: Path | None = None) -> Path:
    """
    自动选择最近处理的试卷目录：
    1) 如果存在 .last_processed，且目录存在则优先使用；
    2) 否则选修改时间最新的子目录；
    3) 若没有子目录，则返回 base_dir 本身。

    Args:
        base_dir: 基准目录，默认为 LEGACY_PDF_IMAGES_DIR

    Returns:
        最近处理的试卷目录路径
    """
    base = base_dir or LEGACY_PDF_IMAGES_DIR
    if not base.exists():
        return base

    lp = base / ".last_processed"
    if lp.is_file():
        try:
            name = lp.read_text(encoding="utf-8").strip()
            candidate = base / name
            if candidate.is_dir():
                return candidate
        except Exception:
            pass

    subdirs = [d for d in base.iterdir() if d.is_dir()]
    if subdirs:
        subdirs.sort(key=lambda d: d.stat().st_mtime, reverse=True)
        return subdirs[0]
    return base


def get_data_dir(subdir: str = "") -> Path:
    """
    获取数据目录路径。

    Args:
        subdir: 子目录名称，如 "input", "output", "interim"

    Returns:
        数据目录路径
    """
    if subdir:
        return DEFAULT_DATA_DIR / subdir
    return DEFAULT_DATA_DIR


def resolve_exam_dir_by_hash(
    clean_name: str,
    file_hash: Optional[str],
    base_dir: Optional[Path] = None,
) -> tuple[Path, str]:
    """
    基于 PDF 内容 hash 解析/创建稳定的试卷目录。

    命名规则：
      - 目录名格式："{clean_name}__{hash前8位}"
      - 相同完整hash -> 复用同一目录
      - 相同clean_name但hash不同 -> 不同目录（这是正确行为，因为是不同的PDF）

    Args:
        clean_name: 清理后的试卷名称（来自文件名）
        file_hash: PDF文件内容的完整sha256 hex字符串
        base_dir: 存放试卷的根目录，默认为 LEGACY_PDF_IMAGES_DIR

    Returns:
        (exam_dir_path, exam_dir_name) 元组
    """
    base = base_dir or LEGACY_PDF_IMAGES_DIR
    base.mkdir(parents=True, exist_ok=True)

    # 如果没有hash，回退到仅使用clean_name（兼容旧行为）
    if not file_hash:
        target = base / clean_name
        target.mkdir(parents=True, exist_ok=True)
        return target, target.name

    hash_prefix = file_hash[:8]
    target_name = f"{clean_name}__{hash_prefix}"
    target = base / target_name

    # 如果目标目录已存在，直接复用
    if target.is_dir():
        return target, target.name

    # 向后兼容：查找已有目录中记录了相同完整hash的
    try:
        from .io import load_job_meta
    except Exception:
        load_job_meta = None  # type: ignore

    for d in base.iterdir():
        if not d.is_dir():
            continue

        # 优先检查 job_meta.json
        if load_job_meta:
            meta_path = d / "job_meta.json"
            if meta_path.is_file():
                try:
                    meta = load_job_meta(meta_path)
                    if meta.get("source_sha256") == file_hash:
                        return d, d.name
                except Exception:
                    pass

        # 兼容旧的 .source_hash 文件
        legacy_hash_file = d / ".source_hash"
        if legacy_hash_file.is_file():
            try:
                if legacy_hash_file.read_text(encoding="utf-8").strip() == file_hash:
                    return d, d.name
            except Exception:
                pass

        # 兼容旧命名风格：clean_name_hashprefix（单下划线）
        if d.name == f"{clean_name}_{hash_prefix}":
            return d, d.name

    # 创建新目录
    target.mkdir(parents=True, exist_ok=True)
    return target, target.name
