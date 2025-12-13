"""
types.py - 类型定义和常量

包含项目中使用的常量、正则表达式和模式定义
"""

import re
from pathlib import Path

# ============ 题号匹配正则 ============
# 支持 "40."、"40．"、"40、" 等格式
QUESTION_HEAD_PATTERN = re.compile(r"(?:^|\n|。)\s*(\d{1,3})[\.．、]\s*")

# 行测卷常见的大题名称关键字
SECTION_HEAD_KEYWORDS = [
    "资料分析",
    "判断推理",
    "言语理解与表达",
    "数量关系",
    "常识判断",
    "科学推理",
]

# 扩展的部分标题/提示模式
SECTION_PART_PATTERN = re.compile(r"第\s*[一二三四五六七八九十]+\s*部分")
QUESTION_RANGE_PATTERN = re.compile(r"回答\s*\d+\s*[-~～－—]\s*\d+\s*题")

DATA_INTRO_KEYWORDS = [
    "资料分析",
    "根据以下资料",
    "根据下列资料",
    "根据所给材料",
    "根据资料",
    "根据材料",
    "下列文字资料",
    "下列图表",
]

# 部分标题模式，如 "一、常识判断"
SECTION_TITLE_PATTERN = re.compile(
    r"^[一二三四五六七八九十]{1,2}\s*[、\.．]\s*("
    + "|".join(SECTION_HEAD_KEYWORDS)
    + r")"
)

# 大题说明中常出现的提示词
SECTION_INTRO_KEYWORDS = ["本部分包括", "本部分内容", "本部分共", "每题", "每道题"]

# 试卷结束标识关键词（单独定义，供其他模块判断试卷结束）
EXAM_END_KEYWORDS = [
    "全部测验到此结束",
    "测验到此结束",
    "试卷结束",
    "考试结束",
    "全部结束",
    "考试到此结束",
    "本试卷结束",
    "答题结束",
]

# 版面噪声关键字（二维码/广告等），用于过滤
# 包含试卷结束标识 + 广告/培训机构相关
NOISE_TEXT_KEYWORDS = EXAM_END_KEYWORDS + [
    "粉笔",
    "扫码",
    "扫码听课",
    "扫码对答案",
    "对答案",
    "二维码",
    "直播",
    "讲解",
    "APP",
    "课程",
    "进群",
    "公众号",
    "海报",
    "广告",
    "扫码查看答案",
    # 常见培训机构名称
    "四海公考",
    "四海",
    "华图",
    "中公",
]

# 默认数据目录
DEFAULT_DATA_DIR = Path("data")
LEGACY_PDF_IMAGES_DIR = Path("pdf_images")
