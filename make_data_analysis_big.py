import json
import re
from pathlib import Path
from typing import Any, Dict, List, Tuple

from PIL import Image
from paddleocr import PPStructureV3


ROOT = Path(".").resolve()
IMG_DIR = ROOT / "pdf_images"

# 资料分析所在的页面范围。
# - 默认：为 None，表示自动检测（优先按“资料分析”标题，其次按试卷尾部页面推断）。
# - 如需强制指定，可改为 ["page_13", "page_14", ...]。
DATA_ANALYSIS_PAGES: List[str] | None = None

# 每道资料分析大题包含的小题数量（用户确认：始终为 5）。
DATA_ANALYSIS_GROUP_SIZE = 5

# 「（一）/ (一) / （二）/ (二) ...」匹配模式
HEADING_PATTERN = re.compile(r"[（(]\s*[一二三四五六七八九十]+\s*[）)]")
DATA_SECTION_KEYWORDS = ["资料分析"]


def load_ppstructure() -> PPStructureV3:
    """
    单独加载 PP-StructureV3，用于在本脚本内重新解析页面，找大题标题位置。
    """
    return PPStructureV3(
        use_doc_orientation_classify=False,
        use_doc_unwarping=False,
    )


def page_index(page_name: str) -> int:
    """page_13 -> 13"""
    try:
        return int(page_name.split("_")[-1])
    except Exception:
        return 0


def crop_and_save(
    page: str, box: Tuple[int, int, int, int], name: str
) -> Tuple[str, Tuple[int, int, int, int]]:
    """
    从整页图片中裁一块，保存到对应 questions_page_XX 目录。
    返回 (图片相对路径, 实际裁剪 box)。
    """
    img_path = IMG_DIR / f"{page}.png"
    if not img_path.is_file():
        raise FileNotFoundError(img_path)

    img = Image.open(img_path)
    x1, y1, x2, y2 = box
    # clamp 到图片尺寸
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
    return str(out_path), box


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
    """
    在 meta.json 中找 footer/number 类 block 的最上方 y，用于避免截到页脚。
    """
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
            f"请先运行: python extract_questions_ppstruct.py {page.split('_')[-1]}"
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
    """
    对若干页面依次跑 PP-StructureV3，返回扁平化的版面块列表 entries，
    以及每页的 footer 顶部位置（优先从 meta.json 中读取）。
    """
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

        # 页脚位置从 meta.json 里提取，兼容我们自己的 footer/number 标注
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
    在扁平化 entries 中查找所有「（一）（二）…」大题标题块，
    返回包含全局索引的列表（已按阅读顺序排序）。
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
    headings.sort(key=lambda h: (page_index(h["page"]), h["bbox"][1], h["global_index"]))
    return headings


def auto_detect_data_analysis_pages(pipeline: PPStructureV3) -> List[str]:
    """
    自动推断资料分析所在的页面范围。

    策略（由强到弱）：
    1. 在所有 page_*.png 中查找包含“资料分析”等关键字的页面，从该页一直到最后一页；
    2. 如果找不到关键词，则退化为“从倒数第 5 页开始到最后一页”；
       （如需更精确或不同试卷结构，可显式修改 DATA_ANALYSIS_PAGES 覆盖。）
    """
    page_files = sorted(IMG_DIR.glob("page_*.png"), key=lambda p: page_index(p.stem))
    page_names = [p.stem for p in page_files]
    if not page_names:
        return []

    # 1) 优先按“资料分析”标题自动识别起始页
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
        # 2) 兜底：从倒数第 5 页（若不足 5 页则从第 1 页）开始视为资料分析范围
        start_index = max(0, len(page_names) - 5)
        auto_pages = page_names[start_index:]
        print(
            f"[data_analysis] 未检测到“资料分析”关键字，"
            f"默认使用末尾页面范围: {auto_pages}"
        )
        return auto_pages

    start_index = page_names.index(start_page)
    auto_pages = page_names[start_index:]
    print(f"[data_analysis] 自动识别资料分析起始页: {start_page}，范围: {auto_pages}")
    return auto_pages


def collect_data_analysis_questions(
    pages: List[str],
) -> List[Dict[str, Any]]:
    """
    从若干页面的 meta.json 中收集所有小题，按阅读顺序排序。
    不再写死 71~75、76~80，只按页面顺序 + y 坐标排列。
    """
    items: List[Dict[str, Any]] = []
    for page in sorted(pages, key=page_index):
        try:
            meta = load_meta(page)
        except FileNotFoundError:
            # 有些页（如资料分析最后一页）可能只有材料没有小题，跳过即可
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
    """
    将资料分析部分的小题按固定 group_size（一般为 5）顺序分组。
    例如 20 道题 -> 4 组，每组 5 题；如果最后一组不足 5 题也仍然作为一组。
    """
    groups: List[List[Dict[str, Any]]] = []
    if group_size <= 0:
        return groups
    for i in range(0, len(questions), group_size):
        groups.append(questions[i : i + group_size])
    return groups


def add_data_analysis_big_questions() -> None:
    """
    自动为资料分析部分生成大题截图和 big_questions 元数据。

    设计要点：
    - 不再写死「71~75」「76~80」等题号，只假定：
      * 资料分析部分在 DATA_ANALYSIS_PAGES 范围内；
      * 每道大题包含 DATA_ANALYSIS_GROUP_SIZE 个小题（当前为 5）；
    - 大题边界由 PP-StructureV3 识别到的「（一）（二）（三）（四）」决定；
    - 每个大题可以跨多页，每页生成一个片段 big_{i}_part{j}.png；
      若只占一页，则命名为 big_{i}.png。
    """

    pipeline = load_ppstructure()

    # 0. 确定资料分析页面范围：优先使用显式配置，否则自动检测
    if DATA_ANALYSIS_PAGES:
        pages = sorted(DATA_ANALYSIS_PAGES, key=page_index)
    else:
        pages = auto_detect_data_analysis_pages(pipeline)

    if not pages:
        print("[data_analysis] 未能确定资料分析页面范围，跳过。")
        return

    # 1. 收集资料分析区间的所有版面块 & 页脚位置
    entries, footer_top_map = collect_layout_entries(pipeline, pages)
    if not entries:
        print("[data_analysis] 未在指定页面范围内解析到版面信息。")
        return

    # 2. 找出所有大题标题（（一）（二）（三）（四）…）
    headings = find_headings(entries)
    if not headings:
        print("[data_analysis] 未识别到任何大题标题（（一）（二）…），跳过。")
        return

    # 3. 收集资料分析部分的小题列表，并按顺序分成若干大题组
    questions = collect_data_analysis_questions(pages)
    if not questions:
        print("[data_analysis] 指定页面中没有找到任何小题。")
        return

    q_groups = chunk_questions_by_group_size(questions, DATA_ANALYSIS_GROUP_SIZE)
    if not q_groups:
        return

    # 大题数量取「标题数量」和「小题组数量」的较小值，避免两者不一致时出错。
    big_count = min(len(headings), len(q_groups))
    if big_count == 0:
        return
    if len(headings) != len(q_groups):
        print(
            f"[data_analysis] 提示：大题标题数={len(headings)}, "
            f"按 {DATA_ANALYSIS_GROUP_SIZE} 题分组后大题数={len(q_groups)}，"
            f"仅对前 {big_count} 组生成截图。"
        )

    # 4. 预载页面尺寸（避免重复打开图片）
    page_sizes: Dict[str, Tuple[int, int]] = {}
    for page in pages:
        img_path = IMG_DIR / f"{page}.png"
        if not img_path.is_file():
            continue
        img = Image.open(img_path)
        page_sizes[page] = (img.width, img.height)

    # 5. 按大题循环：根据标题在 entries 中的位置切分版面块，再按页聚合裁剪
    # 为了不破坏其他类型的大题，这里统一用 id = data_analysis_{i}
    # 并仅写入对应「首个出现页面」的 meta.json。
    metas: Dict[str, Dict[str, Any]] = {}
    for page in pages:
        try:
            meta = load_meta(page)
        except FileNotFoundError:
            continue
        ensure_big_questions_list(meta)
        # 清理旧的 data_analysis_* 记录，避免重复追加
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

        # 该大题对应的小题 qno 列表（按顺序）
        q_group = q_groups[idx]
        qnos = [q.get("qno") for q in q_group if q.get("qno") is not None]

        # 按页聚合该大题的所有版面块，用于决定裁剪区域
        page_to_boxes: Dict[str, List[List[int]]] = {}
        for e in bq_entries:
            page = e["page"]
            label = e.get("label") or ""
            text = e.get("content") or ""
            # 过滤页脚、页码以及带“粉笔”字样的页眉/水印等
            if label in {"footer", "number", "header"}:
                continue
            if isinstance(text, str) and "粉笔" in text:
                continue
            bbox = e.get("bbox")
            if not bbox or not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
                continue
            page_to_boxes.setdefault(page, []).append(
                [int(bbox[0]), int(bbox[1]), int(bbox[2]), int(bbox[3])]
            )

        if not page_to_boxes:
            continue

        # 该大题实际涉及到的页面列表（按页码顺序）
        pages_for_big = sorted(page_to_boxes.keys(), key=page_index)

        # 第一个页面作为「归属页」，在该页的 meta.json 中记录 big_questions 条目
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

            # 全宽 + 适当上下 margin，并避开页脚
            margin_top = 5
            margin_bottom = 10
            top = max(0, union[1] - margin_top)
            bottom = min(height, union[3] + margin_bottom)

            footer_top = footer_top_map.get(page)
            if footer_top is not None:
                bottom = min(bottom, max(0, footer_top - 5))

            crop_box = (0, top, width, bottom)

            # 命名规则：单页 -> big_{i}.png，多页 -> big_{i}_part{j}.png
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

    # 6. 写回 meta.json
    for page, meta in metas.items():
        extra = new_big_questions_by_page.get(page) or []
        if extra:
            meta["big_questions"].extend(extra)
        save_meta(page, meta)


def main() -> None:
    add_data_analysis_big_questions()


if __name__ == "__main__":
    main()
