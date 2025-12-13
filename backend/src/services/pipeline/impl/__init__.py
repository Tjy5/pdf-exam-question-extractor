"""
Pipeline implementation modules.

This package contains the core processing logic for each pipeline step:
- ocr_cache: OCR result caching to avoid redundant PP-StructureV3 calls
- structure_detection: Document structure detection and question graph building
- crop_and_stitch: Image cropping and stitching based on structure
- extract_questions: Question extraction from page images using PP-StructureV3
- compose_long_image: Cross-page question segment composition
"""

from .ocr_cache import (
    run_ocr_with_cache,
    load_ocr_cache,
    save_ocr_cache,
    load_all_ocr_caches,
    is_ocr_complete,
    has_ocr_cache,
)

from .structure_detection import (
    StructureDoc,
    QuestionNode,
    BigQuestion,
    BBox,
    build_structure_doc,
    load_structure_doc,
    save_structure_doc,
    has_structure_doc,
)

from .crop_and_stitch import (
    process_structure_to_images,
    is_crop_complete,
    crop_question_image,
    crop_big_question_image,
)

from .extract_questions import (
    run_extract_questions,
    extract_questions_from_page,
    save_questions_for_page,
)
from .compose_long_image import process_meta_file

__all__ = [
    # ocr_cache
    "run_ocr_with_cache",
    "load_ocr_cache",
    "save_ocr_cache",
    "load_all_ocr_caches",
    "is_ocr_complete",
    "has_ocr_cache",
    # structure_detection
    "StructureDoc",
    "QuestionNode",
    "BigQuestion",
    "BBox",
    "build_structure_doc",
    "load_structure_doc",
    "save_structure_doc",
    "has_structure_doc",
    # crop_and_stitch
    "process_structure_to_images",
    "is_crop_complete",
    "crop_question_image",
    "crop_big_question_image",
    # extract_questions
    "run_extract_questions",
    "extract_questions_from_page",
    "save_questions_for_page",
    # compose_long_image
    "process_meta_file",
]
