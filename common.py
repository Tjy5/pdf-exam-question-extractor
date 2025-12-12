"""
common.py - 向后兼容的导入桥接模块

这个文件是为了保持向后兼容性而创建的。
新代码请直接从 src.common 导入。

原有的 common.py 已经被拆分为多个模块：
- src/common/types.py - 类型定义和常量
- src/common/paths.py - 路径解析工具
- src/common/io.py - 文件IO操作
- src/common/image.py - 图片处理工具
- src/common/ocr_models.py - OCR模型管理
- src/common/utils.py - 通用工具函数

迁移指南：
    旧代码: from common import get_ppstructure, load_meta
    新代码: from src.common import get_ppstructure, load_meta
"""

# 重新导出所有函数，保持向后兼容
from src.common import *  # noqa: F401, F403

# 为了向后兼容，保留原有的 PDF_IMAGES_DIR 变量
from src.common.types import LEGACY_PDF_IMAGES_DIR as PDF_IMAGES_DIR  # noqa: F401
