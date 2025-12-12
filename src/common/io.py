"""
io.py - 文件输入输出工具

提供JSON读写和文件操作相关函数
"""

import json
from pathlib import Path
from typing import Any, Optional


def load_meta(meta_path: Path) -> dict[str, Any]:
    """
    加载 meta.json 文件。

    Args:
        meta_path: meta.json 文件路径

    Returns:
        解析后的字典

    Raises:
        FileNotFoundError: 文件不存在时抛出
    """
    if not meta_path.is_file():
        raise FileNotFoundError(f"meta.json not found: {meta_path}")
    with meta_path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_meta(meta_path: Path, meta: dict[str, Any]) -> None:
    """
    保存 meta.json 文件。

    Args:
        meta_path: 保存路径
        meta: 要保存的字典
    """
    meta_path.parent.mkdir(parents=True, exist_ok=True)
    with meta_path.open("w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)


def load_json(file_path: Path) -> dict[str, Any]:
    """
    加载任意JSON文件。

    Args:
        file_path: JSON文件路径

    Returns:
        解析后的字典

    Raises:
        FileNotFoundError: 文件不存在时抛出
        json.JSONDecodeError: JSON格式错误时抛出
    """
    if not file_path.is_file():
        raise FileNotFoundError(f"JSON file not found: {file_path}")
    with file_path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_json(file_path: Path, data: dict[str, Any], indent: int = 2) -> None:
    """
    保存JSON文件。

    Args:
        file_path: 保存路径
        data: 要保存的字典
        indent: 缩进空格数
    """
    file_path.parent.mkdir(parents=True, exist_ok=True)
    with file_path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=indent)


# ============ Job Meta 管理 ============

JOB_META_FILENAME = "job_meta.json"


def load_job_meta(path: Path, default: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """
    加载 job_meta.json 任务元数据。

    Args:
        path: 试卷目录路径或 job_meta.json 文件路径
        default: 文件不存在时返回的默认值

    Returns:
        任务元数据字典
    """
    # 判断是否为显式的json文件路径
    if path.name == JOB_META_FILENAME or path.suffix == ".json":
        meta_path = path
    else:
        meta_path = path / JOB_META_FILENAME
    try:
        return load_json(meta_path)
    except FileNotFoundError:
        return default or {}


def save_job_meta(path: Path, meta: dict[str, Any], indent: int = 2) -> None:
    """
    保存 job_meta.json 任务元数据。

    Args:
        path: 试卷目录路径或 job_meta.json 文件路径
        meta: 任务元数据字典
        indent: 缩进空格数
    """
    # 判断是否为显式的json文件路径
    if path.name == JOB_META_FILENAME or path.suffix == ".json":
        meta_path = path
    else:
        meta_path = path / JOB_META_FILENAME
    save_json(meta_path, meta, indent=indent)
