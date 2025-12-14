"""
structure_detection.py - 试卷结构检测模块

分析 OCR 结果，检测题目边界、资料分析区域、跨页关系，构建结构文档。
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Tuple

from ....common import (
    page_index,
    QUESTION_HEAD_PATTERN,
    NOISE_TEXT_KEYWORDS,
    EXAM_END_KEYWORDS,
    is_section_boundary_block,
)


# 资料分析标题关键字
DATA_ANALYSIS_KEYWORDS = ["资料分析", "Data Analysis"]

# 资料分析题号范围（用于兜底检测）
DATA_ANALYSIS_QNO_START = 111
DATA_ANALYSIS_QNO_END = 130

# 大题标题模式
BIG_QUESTION_PATTERN = re.compile(
    r"(?:[（(]\s*[一二三四五六七八九十]+\s*[）)])|(?:^[一二三四五六七八九十]{1,2}\s*[、\.．])"
)

# 每道资料分析大题的小题数量
DATA_ANALYSIS_GROUP_SIZE = 5


@dataclass
class BBox:
    """边界框。"""
    page: str
    x1: int
    y1: int
    x2: int
    y2: int

    def to_list(self) -> List[int]:
        return [self.x1, self.y1, self.x2, self.y2]

    @classmethod
    def from_list(cls, page: str, box: List[int]) -> "BBox":
        return cls(page=page, x1=box[0], y1=box[1], x2=box[2], y2=box[3])


@dataclass
class QuestionNode:
    """题目节点。"""
    id: str
    qno: Optional[int]
    kind: Literal["normal", "data_analysis_material", "data_analysis_sub"]
    page_span: List[str]
    bboxes: List[BBox]
    text_preview: str = ""
    parent_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "qno": self.qno,
            "kind": self.kind,
            "page_span": self.page_span,
            "bboxes": [{"page": b.page, "box": b.to_list()} for b in self.bboxes],
            "text_preview": self.text_preview,
            "parent_id": self.parent_id,
        }


@dataclass
class BigQuestion:
    """资料分析大题。"""
    id: str
    order: int
    page_span: List[str]
    material_bboxes: List[BBox]
    sub_question_ids: List[str]
    qno_range: Tuple[int, int]  # (start_qno, end_qno)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "order": self.order,
            "page_span": self.page_span,
            "material_bboxes": [{"page": b.page, "box": b.to_list()} for b in self.material_bboxes],
            "sub_question_ids": self.sub_question_ids,
            "qno_range": list(self.qno_range),
        }


@dataclass
class StructureDoc:
    """结构文档。"""
    questions: List[QuestionNode] = field(default_factory=list)
    big_questions: List[BigQuestion] = field(default_factory=list)
    data_analysis_start_page: Optional[str] = None
    total_pages: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "questions": [q.to_dict() for q in self.questions],
            "big_questions": [bq.to_dict() for bq in self.big_questions],
            "data_analysis_start_page": self.data_analysis_start_page,
            "total_pages": self.total_pages,
        }

    def save(self, path: Path) -> None:
        with path.open("w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)

    @classmethod
    def load(cls, path: Path) -> "StructureDoc":
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)

        doc = cls()
        doc.data_analysis_start_page = data.get("data_analysis_start_page")
        doc.total_pages = data.get("total_pages", 0)

        for q_data in data.get("questions", []):
            bboxes = [
                BBox.from_list(b["page"], b["box"])
                for b in q_data.get("bboxes", [])
            ]
            doc.questions.append(QuestionNode(
                id=q_data["id"],
                qno=q_data.get("qno"),
                kind=q_data["kind"],
                page_span=q_data["page_span"],
                bboxes=bboxes,
                text_preview=q_data.get("text_preview", ""),
                parent_id=q_data.get("parent_id"),
            ))

        for bq_data in data.get("big_questions", []):
            material_bboxes = [
                BBox.from_list(b["page"], b["box"])
                for b in bq_data.get("material_bboxes", [])
            ]
            doc.big_questions.append(BigQuestion(
                id=bq_data["id"],
                order=bq_data["order"],
                page_span=bq_data["page_span"],
                material_bboxes=material_bboxes,
                sub_question_ids=bq_data["sub_question_ids"],
                qno_range=tuple(bq_data["qno_range"]),
            ))

        return doc

    def get_data_analysis_qnos(self) -> set:
        """获取所有属于资料分析的题号。"""
        qnos = set()
        for bq in self.big_questions:
            start, end = bq.qno_range
            for qno in range(start, end + 1):
                qnos.add(qno)
        return qnos

    def get_normal_questions(self) -> List[QuestionNode]:
        """获取所有普通题目（不含资料分析子题）。"""
        return [q for q in self.questions if q.kind == "normal"]


def detect_data_analysis_start(
    ocr_caches: Dict[str, Dict[str, Any]]
) -> Optional[str]:
    """
    检测资料分析区域的起始页。

    Returns:
        资料分析起始页名称，如果未检测到返回 None
    """
    sorted_pages = sorted(ocr_caches.keys(), key=page_index)

    for page_name in sorted_pages:
        cache = ocr_caches[page_name]
        blocks = cache.get("blocks", [])

        for block in blocks:
            text = block.get("content", "")
            if not isinstance(text, str):
                text = str(text)

            # 检查是否包含资料分析关键字
            for keyword in DATA_ANALYSIS_KEYWORDS:
                if keyword in text:
                    # 额外验证：检查是否是标题（通常有"第X部分"）
                    if "部分" in text or block.get("label") == "title":
                        return page_name

    return None


def extract_question_number(text: str) -> Optional[int]:
    """从文本中提取题号。"""
    match = QUESTION_HEAD_PATTERN.match(text.strip())
    if match:
        num_str = match.group(1)
        try:
            return int(num_str)
        except ValueError:
            pass
    return None


def is_data_analysis_qno(qno: int) -> bool:
    """判断题号是否属于资料分析区间。"""
    return DATA_ANALYSIS_QNO_START <= qno <= DATA_ANALYSIS_QNO_END


def is_noise_block(block: Dict[str, Any]) -> bool:
    """判断是否是噪声块（页眉页脚等）。"""
    label = block.get("label", "")
    if label in {"footer", "header", "number"}:
        return True

    text = block.get("content", "")
    if not isinstance(text, str):
        text = str(text)

    for keyword in NOISE_TEXT_KEYWORDS:
        if keyword in text:
            return True

    return False


def is_exam_end_block(block: Dict[str, Any]) -> bool:
    """判断是否是试卷结束标识块。

    注意：需要避免误判，如注意事项中的"宣布考试结束时，应立即停止答题"
    不应被识别为试卷结束标识。真正的结束标识通常是独立的短文本。
    """
    text = block.get("content", "")
    if not isinstance(text, str):
        text = str(text)

    # 去除空白后检查
    normalized = text.strip()
    if not normalized:
        return False

    # 结束标识通常是独立短句，长文本（如说明段落）不视为结束标识
    if len(normalized) > 50:
        return False

    for keyword in EXAM_END_KEYWORDS:
        if keyword in normalized:
            # 关键词应在文本开头或结尾附近，而非嵌入长句中间
            # 例如 "考试结束" 或 "全部测验到此结束！" 是有效的
            # 但 "宣布考试结束时，应立即停止" 不是
            idx = normalized.find(keyword)
            # 关键词前面最多允许少量装饰字符
            if idx <= 10:
                return True

    return False


def build_structure_doc(
    ocr_caches: Dict[str, Dict[str, Any]],
    log: Optional[callable] = None,
) -> StructureDoc:
    """
    构建结构文档。

    Args:
        ocr_caches: {page_name: ocr_cache_data} 字典
        log: 日志回调函数

    Returns:
        StructureDoc 结构文档
    """
    log_fn = log or (lambda m: None)

    doc = StructureDoc()
    doc.total_pages = len(ocr_caches)

    sorted_pages = sorted(ocr_caches.keys(), key=page_index)

    # 1. 检测资料分析起始页（优先标题，失败则后续用题号兜底）
    doc.data_analysis_start_page = detect_data_analysis_start(ocr_caches)
    if doc.data_analysis_start_page:
        log_fn(f"检测到资料分析起始页: {doc.data_analysis_start_page}")
        da_start_idx = page_index(doc.data_analysis_start_page)
    else:
        log_fn("未检测到资料分析区域标题，将使用题号兜底")
        da_start_idx = float("inf")

    # 2. 遍历所有页面提取题目
    all_questions: Dict[int, QuestionNode] = {}  # qno -> QuestionNode
    page_blocks: Dict[str, List[BBox]] = defaultdict(list)  # 记录非噪声块供材料裁剪
    current_qno: Optional[int] = None
    exam_ended = False  # 试卷结束标志

    for page_name in sorted_pages:
        if exam_ended:
            # 试卷已结束，跳过后续页面
            break

        cache = ocr_caches[page_name]
        blocks = cache.get("blocks", [])
        page_idx = page_index(page_name)
        is_data_analysis_page = page_idx >= da_start_idx

        for block in blocks:
            # 检测试卷结束标识
            if is_exam_end_block(block):
                exam_ended = True
                current_qno = None  # 终止当前题目延续
                log_fn(f"检测到试卷结束标识: {page_name}")
                break

            if is_noise_block(block):
                continue

            text = block.get("content", "")
            if not isinstance(text, str):
                text = str(text)

            bbox_raw = block.get("bbox")
            if not bbox_raw or len(bbox_raw) != 4:
                continue

            bbox = BBox.from_list(page_name, [int(x) for x in bbox_raw])

            # 记录所有非噪声块，供后续材料抽取
            page_blocks[page_name].append(bbox)

            # 检查是否是题目开头
            qno = extract_question_number(text)

            if qno is not None:
                # 检查是否属于资料分析题号范围（兜底逻辑）
                is_da_q = is_data_analysis_qno(qno)
                if doc.data_analysis_start_page is None and is_da_q:
                    doc.data_analysis_start_page = page_name
                    da_start_idx = min(da_start_idx, page_idx)
                    is_data_analysis_page = True
                    log_fn(f"通过题号兜底检测到资料分析起始页: {page_name}")

                # 新题目开始
                kind = "data_analysis_sub" if (is_data_analysis_page or is_da_q) else "normal"
                q_id = f"q{qno}"

                if qno not in all_questions:
                    all_questions[qno] = QuestionNode(
                        id=q_id,
                        qno=qno,
                        kind=kind,
                        page_span=[page_name],
                        bboxes=[bbox],
                        text_preview=text[:100],
                    )
                else:
                    # 跨页延续：更新 page_span 和 bboxes
                    existing = all_questions[qno]
                    if page_name not in existing.page_span:
                        existing.page_span.append(page_name)
                    existing.bboxes.append(bbox)

                current_qno = qno

            elif current_qno is not None and current_qno in all_questions:
                # 先检查是否是新部分/新材料的开头
                if is_section_boundary_block(block):
                    # 遇到新部分开头，终止上一题的续接
                    current_qno = None
                    continue

                # 当前题目的延续内容
                existing = all_questions[current_qno]

                # 检查是否是同一页或下一页
                if page_name not in existing.page_span:
                    # 可能是跨页延续
                    last_page = existing.page_span[-1]
                    last_idx = page_index(last_page)
                    curr_idx = page_index(page_name)

                    # 只有相邻页面才视为延续
                    if curr_idx == last_idx + 1:
                        existing.page_span.append(page_name)

                if page_name in existing.page_span:
                    existing.bboxes.append(bbox)

    # 3. 整理题目列表
    doc.questions = [all_questions[qno] for qno in sorted(all_questions.keys())]
    question_by_id = {q.id: q for q in doc.questions}

    # 4. 构建资料分析大题
    # 收集所有资料分析题目（包括题号兜底检测的）
    da_questions = [
        q for q in doc.questions
        if q.kind == "data_analysis_sub" or (q.qno is not None and is_data_analysis_qno(q.qno))
    ]

    if da_questions:
        # 按题号分组
        da_qnos = sorted([q.qno for q in da_questions if q.qno is not None])
        log_fn(f"资料分析小题: {da_qnos[0]} - {da_qnos[-1]}")

        # 按 DATA_ANALYSIS_GROUP_SIZE 分组
        for group_idx in range(0, len(da_qnos), DATA_ANALYSIS_GROUP_SIZE):
            group_qnos = da_qnos[group_idx:group_idx + DATA_ANALYSIS_GROUP_SIZE]
            if not group_qnos:
                continue

            big_order = group_idx // DATA_ANALYSIS_GROUP_SIZE + 1
            big_id = f"data_analysis_{big_order}"

            # 收集该组的页面范围
            group_pages = set()
            sub_ids = []
            for qno in group_qnos:
                q = all_questions.get(qno)
                if q:
                    group_pages.update(q.page_span)
                    sub_ids.append(q.id)
                    q.parent_id = big_id
                    # 确保 kind 正确
                    q.kind = "data_analysis_sub"

            big_q = BigQuestion(
                id=big_id,
                order=big_order,
                page_span=sorted(group_pages, key=page_index),
                material_bboxes=[],
                sub_question_ids=sub_ids,
                qno_range=(group_qnos[0], group_qnos[-1]),
            )
            doc.big_questions.append(big_q)

        log_fn(f"构建了 {len(doc.big_questions)} 个资料分析大题")

        # 5. 补齐资料分析材料区域
        if doc.big_questions and doc.data_analysis_start_page:
            da_start_idx = page_index(doc.data_analysis_start_page)

            # 预计算每个大题的上一个大题的结束位置
            prev_end_page_idx: Optional[int] = None
            prev_end_max_y: Dict[str, int] = {}

            for idx, big_q in enumerate(doc.big_questions):
                sub_nodes = [
                    question_by_id[sid]
                    for sid in big_q.sub_question_ids
                    if sid in question_by_id
                ]

                # 收集子题的页面和最小 y 坐标
                sub_pages = set()
                sub_min_y: Dict[str, int] = {}
                sub_max_y: Dict[str, int] = {}
                for node in sub_nodes:
                    for b in node.bboxes:
                        sub_pages.add(b.page)
                        sub_min_y[b.page] = min(sub_min_y.get(b.page, b.y1), b.y1)
                        sub_max_y[b.page] = max(sub_max_y.get(b.page, b.y2), b.y2)

                first_sub_idx = min(page_index(p) for p in sub_pages) if sub_pages else None

                # 计算当前大题的材料起始位置
                if idx == 0:
                    material_start_idx = da_start_idx
                    material_start_min_y: Dict[str, int] = {}
                else:
                    material_start_idx = prev_end_page_idx if prev_end_page_idx else da_start_idx
                    material_start_min_y = prev_end_max_y.copy()

                # 收集材料页面
                material_pages: List[str] = []
                for page_name in sorted_pages:
                    p_idx = page_index(page_name)
                    if p_idx < material_start_idx or first_sub_idx is None:
                        continue
                    # 材料区域：从当前大题起始到子题所在页
                    if p_idx <= first_sub_idx:
                        material_pages.append(page_name)
                    elif page_name in sub_pages:
                        # 子题跨越的页面也包含在内
                        material_pages.append(page_name)

                # 收集材料区域的 bboxes
                material_boxes: List[BBox] = []
                for page_name in material_pages:
                    blocks = page_blocks.get(page_name, [])
                    p_idx = page_index(page_name)
                    cutoff_top = material_start_min_y.get(page_name)
                    cutoff_bottom = sub_min_y.get(page_name)

                    for b in blocks:
                        # 跳过上一大题子题区域内的块
                        if cutoff_top is not None and p_idx == material_start_idx and b.y1 < cutoff_top:
                            continue
                        # 跳过当前大题子题区域内的块
                        if cutoff_bottom is not None and b.y2 > cutoff_bottom:
                            continue
                        material_boxes.append(b)

                if material_boxes:
                    big_q.material_bboxes = material_boxes
                    big_q.page_span = sorted(
                        set(big_q.page_span) | {b.page for b in material_boxes},
                        key=page_index,
                    )

                # 更新下一个大题的起始位置（当前大题子题的结束位置）
                if sub_pages:
                    prev_end_page_idx = max(page_index(p) for p in sub_pages)
                    prev_end_max_y = sub_max_y.copy()

    normal_count = len([q for q in doc.questions if q.kind == "normal"])
    log_fn(f"共检测到 {normal_count} 道普通题目")

    return doc


def get_structure_path(workdir: Path) -> Path:
    """获取结构文档路径。"""
    return workdir / "structure.json"


def has_structure_doc(workdir: Path) -> bool:
    """检查结构文档是否存在。"""
    return get_structure_path(workdir).is_file()


def load_structure_doc(workdir: Path) -> Optional[StructureDoc]:
    """加载结构文档。"""
    path = get_structure_path(workdir)
    if not path.is_file():
        return None
    return StructureDoc.load(path)


def save_structure_doc(workdir: Path, doc: StructureDoc) -> Path:
    """保存结构文档。"""
    path = get_structure_path(workdir)
    doc.save(path)
    return path
