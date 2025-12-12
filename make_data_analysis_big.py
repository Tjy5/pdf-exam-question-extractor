import json
import re
import sys
import argparse
from pathlib import Path
from typing import Any, Dict, List, Tuple

from PIL import Image

# 公共模块
from common import (
    page_index,
    get_ppstructure,
    layout_blocks_from_doc,
    load_meta as _load_meta,
    save_meta as _save_meta,
    get_meta_path,
    union_boxes,
    crop_page_and_save,
    find_footer_top_from_meta,
    auto_latest_exam_dir,
    NOISE_TEXT_KEYWORDS,
)


ROOT = Path(".").resolve()
DEFAULT_IMG_DIR = ROOT / "pdf_images"

# 手动指定资料分析页面（如不为 None，则跳过自动识别）
DATA_ANALYSIS_PAGES: List[str] | None = None
# 每道资料分析大题对应的小题数量（默认为 5）
DATA_ANALYSIS_GROUP_SIZE = 5
# 大题标题模式：
# - “（一）……”“(二) ……”
# - “一、根据所给材料，回答……题。”
HEADING_PATTERN = re.compile(
    r"(?:[（(]\s*[一二三四五六七八九十]+\s*[）)])|(?:^[一二三四五六七八九十]{1,2}\s*[、\.．])"
)
# 资料分析段落关键字（用于粗定位起始页面）
DATA_SECTION_KEYWORDS = ["资料分析"]

# 全局：当前处理的试卷目录
IMG_DIR = DEFAULT_IMG_DIR


def load_meta(page: str) -> Dict[str, Any]:
    """加载指定页面的 meta.json"""
    meta_path = get_meta_path(IMG_DIR, page)
    if not meta_path.is_file():
        raise FileNotFoundError(
            f"meta.json not found for {page}, "
            f"请先运行: python extract_questions_ppstruct.py --dir {IMG_DIR} {page.split('_')[-1]}"
        )
    return _load_meta(meta_path)


def save_meta(page: str, meta: Dict[str, Any]) -> None:
    """保存指定页面的 meta.json"""
    meta_path = get_meta_path(IMG_DIR, page)
    _save_meta(meta_path, meta)


def ensure_big_questions_list(meta: Dict[str, Any]) -> None:
    """确保 meta 中存在 big_questions 列表"""
    if "big_questions" not in meta:
        meta["big_questions"] = []


def collect_layout_entries(
    pipeline: Any, pages: List[str]
) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    """
    对指定页面范围跑 PP-StructureV3，收集所有版面块（entries），
    同时基于已有 meta.json 推断每页页脚位置。
    """
    entries: List[Dict[str, Any]] = []
    footer_top_map: Dict[str, int] = {}

    for page in sorted(pages, key=page_index):
        img_path = IMG_DIR / f"{page}.png"
        if not img_path.is_file():
            continue

        doc = pipeline.predict(str(img_path))[0]
        blocks = layout_blocks_from_doc(doc)
        for blk in blocks:
            bbox = blk.get("bbox")
            if not bbox or not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
                continue
            label = blk.get("label") or ""
            content = blk.get("content", "")
            if not isinstance(content, str):
                content = str(content)
            entries.append(
                {
                    "page": page,
                    "bbox": [int(bbox[0]), int(bbox[1]), int(bbox[2]), int(bbox[3])],
                    "label": label,
                    "content": content,
                }
            )

        try:
            meta = load_meta(page)
            footer_top = find_footer_top_from_meta(meta)
            if footer_top is not None:
                footer_top_map[page] = footer_top
        except FileNotFoundError:
            pass

    return entries, footer_top_map


def find_headings(entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    在版面 entries 中查找“大题标题”，例如“（一）xxx”“(二) xxx”。
    """
    headings: List[Dict[str, Any]] = []
    for idx, e in enumerate(entries):
        text = e.get("content") or ""
        if not isinstance(text, str):
            continue
        if HEADING_PATTERN.search(text):
            headings.append(
                {
                    "global_index": idx,
                    "page": e["page"],
                    "bbox": e["bbox"],
                    "text": text,
                }
            )
    headings.sort(
        key=lambda h: (page_index(h["page"]), h["bbox"][1], h["global_index"])
    )
    return headings


def auto_detect_data_analysis_pages(pipeline: Any) -> List[str]:
    """
    自动推断资料分析所在页面范围：
    1）优先在所有 page_*.png 中搜索包含“资料分析”等关键字的页面；
    2）若未命中，则退而取“最后若干页”（默认 10 页），用于大多数行测卷。
    """
    page_files = sorted(IMG_DIR.glob("page_*.png"), key=lambda p: page_index(p.stem))
    page_names = [p.stem for p in page_files]
    if not page_names:
        return []

    start_page: str | None = None
    for name, path in zip(page_names, page_files):
        try:
            doc = pipeline.predict(str(path))[0]
        except Exception:
            continue
        blocks = layout_blocks_from_doc(doc)
        for blk in blocks:
            text = blk.get("content", "")
            if not isinstance(text, str):
                text = str(text)
            if any(k in text for k in DATA_SECTION_KEYWORDS):
                start_page = name
                break
        if start_page:
            break

    if start_page is None:
        tail = 10
        start_index = max(0, len(page_names) - tail)
        auto_pages = page_names[start_index:]
        print(f"[data_analysis] 未检测到关键字，默认使用末尾 {tail} 页范围: {auto_pages}")
        return auto_pages

    start_index = page_names.index(start_page)
    auto_pages = page_names[start_index:]
    print(
        f"[data_analysis] 自动识别起始页: {start_page}，范围: {auto_pages}"
    )
    return auto_pages


def collect_data_analysis_questions(pages: List[str]) -> List[Dict[str, Any]]:
    """
    从指定页面范围内收集所有小题（qno + page + bbox）。
    """
    items: List[Dict[str, Any]] = []
    for page in sorted(pages, key=page_index):
        try:
            meta = load_meta(page)
        except FileNotFoundError:
            continue
        for q in meta.get("questions", []):
            bbox = q.get("crop_box_blocks") or q.get("crop_box_image")
            if not bbox or not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
                continue
            items.append(
                {
                    "page": page,
                    "qno": q.get("qno"),
                    "bbox": [int(bbox[0]), int(bbox[1]), int(bbox[2]), int(bbox[3])],
                }
            )
    items.sort(key=lambda x: (page_index(x["page"]), x["bbox"][1], x["bbox"][0]))
    return items


def chunk_questions_by_group_size(
    questions: List[Dict[str, Any]], group_size: int
) -> List[List[Dict[str, Any]]]:
    """按固定题量切分小题列表，例如每 5 题一组。"""
    groups: List[List[Dict[str, Any]]] = []
    if group_size <= 0:
        return groups
    for i in range(0, len(questions), group_size):
        groups.append(questions[i : i + group_size])
    return groups


def add_data_analysis_big_questions() -> None:
    """
    生成资料分析大题结构：
    - 正常情况：依赖“（一）（二）……”等标题精确裁剪材料区域；
    - 兜底情况：标题缺失时，按固定题量直接构造大题，并复用每道小题自身图片。
    """
    pipeline = get_ppstructure()

    if DATA_ANALYSIS_PAGES:
        pages = sorted(DATA_ANALYSIS_PAGES, key=page_index)
    else:
        pages = auto_detect_data_analysis_pages(pipeline)

    if not pages:
        print("[data_analysis] 未确定页面范围，跳过。")
        return

    entries, footer_top_map = collect_layout_entries(pipeline, pages)
    if not entries:
        print("[data_analysis] 未解析到版面信息。")
        return

    headings = find_headings(entries)
    questions = collect_data_analysis_questions(pages)
    if not questions:
        print("[data_analysis] 未找到小题。")
        return

    q_groups = chunk_questions_by_group_size(questions, DATA_ANALYSIS_GROUP_SIZE)
    if not q_groups:
        print(
            "[data_analysis] 小题分组结果为空，可能 DATA_ANALYSIS_GROUP_SIZE 配置不合理。"
        )
        return

    use_headings = bool(headings)
    if use_headings:
        big_count = min(len(headings), len(q_groups))
        if big_count == 0:
            print("[data_analysis] 大题标题数量为 0。")
            return
    else:
        print(
            f"[data_analysis] 未识别到大题标题，将按每 {DATA_ANALYSIS_GROUP_SIZE} 道小题一组直接构造大题（不使用标题区域）。"
        )

    # 准备页面尺寸与 meta
    page_sizes: Dict[str, Tuple[int, int]] = {}
    for page in pages:
        img_path = IMG_DIR / f"{page}.png"
        if not img_path.is_file():
            continue
        img = Image.open(img_path)
        page_sizes[page] = (img.width, img.height)

    metas: Dict[str, Dict[str, Any]] = {}
    for page in pages:
        try:
            meta = load_meta(page)
        except FileNotFoundError:
            continue
        ensure_big_questions_list(meta)
        # 清理旧的 data_analysis_* 记录
        meta["big_questions"] = [
            bq
            for bq in meta["big_questions"]
            if not str(bq.get("id", "")).startswith("data_analysis_")
        ]
        metas[page] = meta

    new_big_questions_by_page: Dict[str, List[Dict[str, Any]]] = {
        page: [] for page in metas.keys()
    }

    if use_headings:
        # 正常路径：依赖版面中的“（一）（二）…”等大题标题，精确裁剪材料区域。
        for idx in range(big_count):
            heading = headings[idx]
            start_idx = heading["global_index"]
            end_idx = (
                headings[idx + 1]["global_index"]
                if idx + 1 < len(headings)
                else len(entries)
            )
            bq_entries = entries[start_idx:end_idx]
            q_group = q_groups[idx]
            qnos = [q.get("qno") for q in q_group if q.get("qno") is not None]

            # 检测标题页上方的材料块（图表/表格），某些试卷排版是"图表在标题上方"
            heading_page = heading["page"]
            heading_top = int(heading["bbox"][1])
            material_labels_above = {"chart", "table", "image", "figure"}
            above_material_boxes: List[List[int]] = []
            prev_boundary = headings[idx - 1]["global_index"] if idx > 0 else 0
            for e2 in entries[prev_boundary:end_idx]:
                if e2.get("page") != heading_page:
                    continue
                label2 = (e2.get("label") or "").lower()
                if label2 not in material_labels_above:
                    continue
                # 过滤噪声（水印、logo等）
                text2 = e2.get("content") or ""
                if isinstance(text2, str) and any(k in text2 for k in NOISE_TEXT_KEYWORDS):
                    continue
                bbox2 = e2.get("bbox")
                if not bbox2 or not isinstance(bbox2, (list, tuple)) or len(bbox2) != 4:
                    continue
                box2 = [int(bbox2[0]), int(bbox2[1]), int(bbox2[2]), int(bbox2[3])]
                # 仅取顶边位于标题上方的材料块（使用顶边判断更宽松）
                if box2[1] < heading_top:
                    above_material_boxes.append(box2)

            # 先按页面收集文本块和其他块，避免将页面底部的"扫码做题 / 对答案"等广告区域纳入大题
            page_to_text_boxes: Dict[str, List[List[int]]] = {}
            page_to_other_boxes: Dict[str, List[List[int]]] = {}

            for e in bq_entries:
                page = e["page"]
                label = e.get("label") or ""
                text = e.get("content") or ""
                if label in {"footer", "number", "header"}:
                    continue
                # 过滤粉笔水印、“扫码对答案”等广告文本
                if isinstance(text, str) and any(
                    k in text for k in NOISE_TEXT_KEYWORDS
                ):
                    continue
                bbox = e.get("bbox")
                if (
                    not bbox
                    or not isinstance(bbox, (list, tuple))
                    or len(bbox) != 4
                ):
                    continue
                box = [int(bbox[0]), int(bbox[1]), int(bbox[2]), int(bbox[3])]

                if label == "text":
                    page_to_text_boxes.setdefault(page, []).append(box)
                else:
                    page_to_other_boxes.setdefault(page, []).append(box)

            # 以文本块为主，附带位于文本区域垂直范围内的非文本块（图表/表格），
            # 使用垂直方向相邻判断（允许一定间隙），排除分离的底部广告区域。
            vertical_gap = 200  # 允许的垂直间隙（像素）
            page_to_boxes: Dict[str, List[List[int]]] = {}
            for page, text_boxes in page_to_text_boxes.items():
                if not text_boxes:
                    continue
                # 文本区域整体包围盒
                t_union = union_boxes(text_boxes)
                if t_union is None:
                    continue
                tx1, ty1, tx2, ty2 = t_union

                fused: List[List[int]] = list(text_boxes)
                for box in page_to_other_boxes.get(page, []):
                    x1, y1, x2, y2 = box
                    # 垂直方向相邻或重叠判断，排除远离正文的广告
                    if not (x2 < tx1 or x1 > tx2) and not (y2 < ty1 - vertical_gap or y1 > ty2 + vertical_gap):
                        fused.append(box)
                page_to_boxes[page] = fused

            # 如果标题页没有被文本框选中，至少用标题框把它纳入，避免材料起始页缺失
            if heading_page not in page_to_boxes and heading_page in page_sizes:
                hb = heading["bbox"]
                hx1, hy1, hx2, hy2 = int(hb[0]), int(hb[1]), int(hb[2]), int(hb[3])
                pad = 20
                page_to_boxes[heading_page] = [
                    [max(0, hx1 - pad), max(0, hy1 - pad), hx2 + pad, hy2 + pad]
                ]

            # 将标题上方的材料块（图表/表格）并入裁剪区域
            if above_material_boxes:
                page_to_boxes.setdefault(heading_page, []).extend(above_material_boxes)

            if not page_to_boxes:
                continue

            pages_for_big = sorted(page_to_boxes.keys(), key=page_index)
            # 将材料页限制在“最后一道小题所在页”之前，防止把后续广告页并入
            question_pages = sorted(
                {q.get("page") for q in q_group if q.get("page")}, key=page_index
            )
            if question_pages:
                max_q_page_idx = page_index(question_pages[-1])
                pages_for_big = [
                    p for p in pages_for_big if page_index(p) <= max_q_page_idx
                ]
            if not pages_for_big:
                continue

            # 过滤疑似纯广告页：文本高度占比很小且包含广告关键词
            filtered_pages: List[str] = []
            for p in pages_for_big:
                boxes = page_to_boxes.get(p) or []
                size = page_sizes.get(p)
                if not boxes or not size:
                    continue
                width, height = size
                u = union_boxes(boxes)
                if u is None:
                    continue
                _, top, _, bottom = u
                span = bottom - top if bottom > top else 0
                has_noise = False
                for e in bq_entries:
                    if e.get("page") != p:
                        continue
                    txt = e.get("content") or ""
                    if isinstance(txt, str) and any(k in txt for k in NOISE_TEXT_KEYWORDS):
                        has_noise = True
                        break
                if has_noise and height and span / height < 0.2:
                    continue  # skip this page
                filtered_pages.append(p)

            pages_for_big = filtered_pages
            if not pages_for_big:
                continue

            # anchor_page 必须有 meta.json，若标题页没有题目导致 meta 缺失，则向后找有 meta 的页
            anchor_page = None
            for p in pages_for_big:
                if p in metas:
                    anchor_page = p
                    break
            if anchor_page is None:
                # 实在找不到 meta，就退回标题所在页
                anchor_page = pages_for_big[0]
            big_id = f"data_analysis_{idx + 1}"

            segments: List[Dict[str, Any]] = []
            part_idx = 1

            for page in pages_for_big:
                boxes = page_to_boxes.get(page) or []
                size = page_sizes.get(page)
                if not boxes or not size:
                    continue
                width, height = size

                union = union_boxes(boxes)
                if union is None:
                    continue

                margin_top = 5
                margin_bottom = 10
                # 对于大题起始页，顶部从“（一）/（二）…”的标题位置开始，
                # 这样可以把材料表格等内容一并包含进来；
                # 其它页仍然以本页正文文本的最小 y 作为上边界。
                if page == heading_page:
                    top_source = min(heading_top, int(union[1]))
                else:
                    top_source = int(union[1])
                top = max(0, top_source - margin_top)
                bottom = min(height, union[3] + margin_bottom)

                footer_top = footer_top_map.get(page)
                if footer_top is not None:
                    bottom = min(bottom, max(0, footer_top - 5))

                crop_box = (0, top, width, bottom)

                if len(pages_for_big) == 1:
                    filename = f"big_{idx + 1}.png"
                else:
                    filename = f"big_{idx + 1}_part{part_idx}.png"
                part_idx += 1

                rel_path, final_box = crop_page_and_save(
                    img_dir=IMG_DIR, page=page, box=crop_box, name=filename
                )
                segments.append(
                    {
                        "page": page,
                        "image": rel_path,
                        "box": list(final_box),
                    }
                )

            if not segments:
                continue

            bq_record = {
                "id": big_id,
                "type": "data_analysis",
                "pages": pages_for_big,
                "qnos": qnos,
                "segments": segments,
            }
            new_big_questions_by_page.setdefault(anchor_page, []).append(bq_record)
    else:
        # 兜底路径：没有识别到“（一）（二）…”等标题时，按固定题量直接构造大题，
        # 不额外裁剪材料区域，而是复用每道小题自身的图片（long_image 优先）。
        for idx, q_group in enumerate(q_groups):
            qnos = [q.get("qno") for q in q_group if q.get("qno") is not None]
            if not qnos:
                continue

            pages_for_big = sorted(
                {q["page"] for q in q_group if q.get("page")}, key=page_index
            )
            if not pages_for_big:
                continue

            segments: List[Dict[str, Any]] = []
            for q in q_group:
                page = q.get("page")
                qno = q.get("qno")
                if page is None or qno is None:
                    continue
                meta = metas.get(page)
                if not meta:
                    continue
                q_entry = None
                for item in meta.get("questions", []):
                    if item.get("qno") == qno:
                        q_entry = item
                        break
                if not q_entry:
                    continue

                img_path_str = q_entry.get("long_image") or q_entry.get("image")
                box = q_entry.get("crop_box_image") or q_entry.get("crop_box_blocks")
                if not img_path_str or not box:
                    continue

                segments.append(
                    {
                        "page": page,
                        "image": img_path_str,
                        "box": list(box),
                    }
                )

            if not segments:
                continue

            big_id = f"data_analysis_{idx + 1}"
            anchor_page = pages_for_big[0]
            bq_record = {
                "id": big_id,
                "type": "data_analysis",
                "pages": pages_for_big,
                "qnos": qnos,
                "segments": segments,
            }
            new_big_questions_by_page.setdefault(anchor_page, []).append(bq_record)

    # 写回 meta.json
    for page, meta in metas.items():
        extra = new_big_questions_by_page.get(page) or []
        if extra:
            meta["big_questions"].extend(extra)
        save_meta(page, meta)


def parse_args():
    parser = argparse.ArgumentParser(description="Make data analysis big questions.")
    parser.add_argument(
        "--dir",
        type=str,
        default=None,
        help="Directory containing page_*.png; if omitted auto-select latest under pdf_images",
    )
    return parser.parse_args()


def main() -> None:
    global IMG_DIR
    args = parse_args()
    IMG_DIR = Path(args.dir).resolve() if args.dir else auto_latest_exam_dir().resolve()

    if not IMG_DIR.is_dir():
        print(f"错误: 目录不存在: {IMG_DIR}")
        sys.exit(1)

    print(f"正在处理目录: {IMG_DIR}")
    add_data_analysis_big_questions()


if __name__ == "__main__":
    main()
