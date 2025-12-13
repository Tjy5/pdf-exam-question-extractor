"""
common模块 - 公共工具函数和常量

这个模块提供了项目中各脚本共用的工具函数，包括：
- 类型定义和常量（types）
- 路径解析工具（paths）
- 文件IO操作（io）
- 图片处理工具（image）
- OCR模型管理（ocr_models）
- 通用工具函数（utils）

使用示例：
    from backend.src.common import get_ppstructure, load_meta, crop_and_save
    from backend.src.common.types import QUESTION_HEAD_PATTERN
    from backend.src.common.paths import page_index
"""

# 从各子模块导入常用函数和类
from .types import (
    QUESTION_HEAD_PATTERN,
    SECTION_HEAD_KEYWORDS,
    SECTION_PART_PATTERN,
    QUESTION_RANGE_PATTERN,
    DATA_INTRO_KEYWORDS,
    SECTION_TITLE_PATTERN,
    SECTION_INTRO_KEYWORDS,
    EXAM_END_KEYWORDS,
    NOISE_TEXT_KEYWORDS,
    DEFAULT_DATA_DIR,
    LEGACY_PDF_IMAGES_DIR,
)

from .paths import (
    page_index,
    resolve_image_path,
    get_meta_path,
    iter_meta_paths,
    auto_latest_exam_dir,
    get_data_dir,
    resolve_exam_dir_by_hash,
)

from .io import (
    load_meta,
    save_meta,
    load_json,
    save_json,
    load_job_meta,
    save_job_meta,
    JOB_META_FILENAME,
)

from .image import (
    union_boxes,
    crop_and_save,
    crop_page_and_save,
    compose_vertical,
    compute_smart_crop_box,
    find_footer_top_from_meta,
)

from .ocr_models import (
    get_offline_model_path,
    get_ppstructure,
    layout_blocks_from_doc,
)

from .utils import (
    is_section_boundary_block,
    detect_section_boundaries,
    detect_continuation_blocks,
)

__all__ = [
    # types
    "QUESTION_HEAD_PATTERN",
    "SECTION_HEAD_KEYWORDS",
    "SECTION_PART_PATTERN",
    "QUESTION_RANGE_PATTERN",
    "DATA_INTRO_KEYWORDS",
    "SECTION_TITLE_PATTERN",
    "SECTION_INTRO_KEYWORDS",
    "EXAM_END_KEYWORDS",
    "NOISE_TEXT_KEYWORDS",
    "DEFAULT_DATA_DIR",
    "LEGACY_PDF_IMAGES_DIR",
    # paths
    "page_index",
    "resolve_image_path",
    "get_meta_path",
    "iter_meta_paths",
    "auto_latest_exam_dir",
    "get_data_dir",
    "resolve_exam_dir_by_hash",
    # io
    "load_meta",
    "save_meta",
    "load_json",
    "save_json",
    "load_job_meta",
    "save_job_meta",
    "JOB_META_FILENAME",
    # image
    "union_boxes",
    "crop_and_save",
    "crop_page_and_save",
    "compose_vertical",
    "compute_smart_crop_box",
    "find_footer_top_from_meta",
    # ocr_models
    "get_offline_model_path",
    "get_ppstructure",
    "layout_blocks_from_doc",
    # utils
    "is_section_boundary_block",
    "detect_section_boundaries",
    "detect_continuation_blocks",
]
