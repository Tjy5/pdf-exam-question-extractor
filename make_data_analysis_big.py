import json
import re
import sys
import argparse
from pathlib import Path
from typing import Any, Dict, List, Tuple

from PIL import Image
from paddleocr import PPStructureV3


# 修改 1: 不再硬编码，改由参数或默认值决定
ROOT = Path(".").resolve()
DEFAULT_IMG_DIR = ROOT / "pdf_images"

DATA_ANALYSIS_PAGES: List[str] | None = None
DATA_ANALYSIS_GROUP_SIZE = 5
HEADING_PATTERN = re.compile(r"[（(]\s*[一二三四五六七八九十]+\s*[）)]")
DATA_SECTION_KEYWORDS = ["资料分析"]
# 一些可以视为“噪声/广告”的文本关键字，用于过滤二维码广告页等
NOISE_TEXT_KEYWORDS = ["粉笔", "扫码", "对答案", "二维码", "客户端"]

# 全局变量，将在 main 中根据参数初始化
IMG_DIR = DEFAULT_IMG_DIR


def load_ppstructure() -> PPStructureV3:
    return PPStructureV3(
        use_doc_orientation_classify=False,
        use_doc_unwarping=False,
    )


def page_index(page_name: str) -> int:
    try:
        return int(page_name.split("_")[-1])
    except Exception:
        return 0


def crop_and_save(
    page: str, box: Tuple[int, int, int, int], name: str
) -> Tuple[str, Tuple[int, int, int, int]]:
    img_path = IMG_DIR / f"{page}.png"
    if not img_path.is_file():
        raise FileNotFoundError(img_path)

    img = Image.open(img_path)
    x1, y1, x2, y2 = box
    x1 = max(0, min(x1, img.width))
    x2 = max(0, min(x2, img.width))
    y1 = max(0, min(y1, img.height))
    y2 = max(0, min(y2, img.height))
    if x2 <= x1:
        x1, x2 = 0, img.width
    if y2 <= y1:
        y1, y2 = 0, img.height
    box = (x1, y1, x2, y2)
    crop = img.crop(box)

    out_dir = IMG_DIR / f"questions_{page}"
    out_dir.mkdir(parents=True, exist_ok=True)

    out_path = out_dir / name
    crop.save(out_path)
    
    # 返回相对路径
    try:
        rel_path = out_path.relative_to(IMG_DIR.parent)
    except ValueError:
        rel_path = out_path
    
    return str(rel_path), box


def union_boxes(boxes: List[List[int]] | List[Tuple[int, int, int, int]]):
    xs: List[int] = []
    ys: List[int] = []
    for b in boxes:
        xs += [int(b[0]), int(b[2])]
        ys += [int(b[1]), int(b[3])]
    if not xs:
        return None
    return (min(xs), min(ys), max(xs), max(ys))


def find_footer_top_from_meta(meta: Dict[str, Any]) -> int | None:
    ys: List[int] = []
    for q in meta.get("questions", []):
        for blk in q.get("other_blocks", []):
            if blk.get("label") in {"footer", "number"}:
                bbox = blk.get("bbox")
                if bbox and isinstance(bbox, (list, tuple)) and len(bbox) == 4:
                    ys.append(int(bbox[1]))
    return min(ys) if ys else None


def load_meta(page: str) -> Dict[str, Any]:
    meta_path = IMG_DIR / f"questions_{page}" / "meta.json"
    if not meta_path.is_file():
        raise FileNotFoundError(
            f"meta.json not found for {page}, "
            f"请先运行: python extract_questions_ppstruct.py --dir {IMG_DIR} {page.split('_')[-1]}"
        )
    with meta_path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_meta(page: str, meta: Dict[str, Any]) -> None:
    meta_path = IMG_DIR / f"questions_{page}" / "meta.json"
    with meta_path.open("w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)


def ensure_big_questions_list(meta: Dict[str, Any]) -> None:
    if "big_questions" not in meta:
        meta["big_questions"] = []


def collect_layout_entries(
    pipeline: PPStructureV3, pages: List[str]
) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    entries: List[Dict[str, Any]] = []
    footer_top_map: Dict[str, int] = {}

    for page in sorted(pages, key=page_index):
        img_path = IMG_DIR / f"{page}.png"
        if not img_path.is_file():
            continue

        doc = pipeline.predict(str(img_path))[0]
        parsing_list = doc.get("parsing_res_list") or []
        for blk in parsing_list:
            if hasattr(blk, "to_dict"):
                info = blk.to_dict()
            else:
                info = getattr(blk, "__dict__", {})
            bbox = info.get("bbox")
            if not bbox or not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
                continue
            label = info.get("label") or ""
            content = info.get("content", "")
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
    headings.sort(key=lambda h: (page_index(h["page"]), h["bbox"][1], h["global_index"]))
    return headings


def auto_detect_data_analysis_pages(pipeline: PPStructureV3) -> List[str]:
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
        parsing_list = doc.get("parsing_res_list") or []
        for blk in parsing_list:
            if hasattr(blk, "to_dict"):
                info = blk.to_dict()
            else:
                info = getattr(blk, "__dict__", {})
            text = info.get("content", "")
            if not isinstance(text, str):
                text = str(text)
            if any(k in text for k in DATA_SECTION_KEYWORDS):
                start_page = name
                break
        if start_page:
            break

    if start_page is None:
        start_index = max(0, len(page_names) - 5)
        auto_pages = page_names[start_index:]
        print(f"[data_analysis] 未检测到关键字，默认使用范围: {auto_pages}")
        return auto_pages

    start_index = page_names.index(start_page)
    auto_pages = page_names[start_index:]
    print(f"[data_analysis] 自动识别起始页: {start_page}，范围: {auto_pages}")
    return auto_pages


def collect_data_analysis_questions(
    pages: List[str],
) -> List[Dict[str, Any]]:
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
    groups: List[List[Dict[str, Any]]] = []
    if group_size <= 0:
        return groups
    for i in range(0, len(questions), group_size):
        groups.append(questions[i : i + group_size])
    return groups


def add_data_analysis_big_questions() -> None:
    pipeline = load_ppstructure()

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
    if not headings:
        print("[data_analysis] 未识别到大题标题。")
        return

    questions = collect_data_analysis_questions(pages)
    if not questions:
        print("[data_analysis] 未找到小题。")
        return

    q_groups = chunk_questions_by_group_size(questions, DATA_ANALYSIS_GROUP_SIZE)
    if not q_groups:
        return

    big_count = min(len(headings), len(q_groups))
    if big_count == 0:
        return

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
        meta["big_questions"] = [
            bq
            for bq in meta["big_questions"]
            if not str(bq.get("id", "")).startswith("data_analysis_")
        ]
        metas[page] = meta

    new_big_questions_by_page: Dict[str, List[Dict[str, Any]]] = {
        page: [] for page in metas.keys()
    }

    for idx in range(big_count):
        heading = headings[idx]
        start_idx = heading["global_index"]
        end_idx = headings[idx + 1]["global_index"] if idx + 1 < len(headings) else len(
            entries
        )
        bq_entries = entries[start_idx:end_idx]
        q_group = q_groups[idx]
        qnos = [q.get("qno") for q in q_group if q.get("qno") is not None]

        # 先按页面收集文本块和其他块，避免将页面底部的“扫码做题 / 对答案”等广告区域纳入大题
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
            if not bbox or not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
                continue
            box = [int(bbox[0]), int(bbox[1]), int(bbox[2]), int(bbox[3])]

            if label == "text":
                page_to_text_boxes.setdefault(page, []).append(box)
            else:
                page_to_other_boxes.setdefault(page, []).append(box)

        # 以文本块为主，附带与文本区域相交的非文本块（例如图表），
        # 排除与正文区域分离的底部二维码等广告区域。
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
                # 简单矩形相交判断，只保留与正文区域重叠的图表等
                if not (x2 < tx1 or x1 > tx2 or y2 < ty1 or y1 > ty2):
                    fused.append(box)
            page_to_boxes[page] = fused

        if not page_to_boxes:
            continue

        pages_for_big = sorted(page_to_boxes.keys(), key=page_index)
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
            top = max(0, union[1] - margin_top)
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

            rel_path, final_box = crop_and_save(page=page, box=crop_box, name=filename)
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
        if anchor_page in new_big_questions_by_page:
            new_big_questions_by_page[anchor_page].append(bq_record)
        else:
            new_big_questions_by_page[anchor_page] = [bq_record]

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
        default="pdf_images", 
        help="Input directory containing page_*.png"
    )
    return parser.parse_args()


def main() -> None:
    global IMG_DIR
    args = parse_args()
    IMG_DIR = Path(args.dir).resolve()
    
    if not IMG_DIR.is_dir():
        print(f"错误: 目录不存在: {IMG_DIR}")
        sys.exit(1)

    print(f"正在处理目录: {IMG_DIR}")
    add_data_analysis_big_questions()


if __name__ == "__main__":
    main()
