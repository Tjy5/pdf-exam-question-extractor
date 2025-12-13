#!/usr/bin/env python
"""检查题目提取的完整性"""
import json
from pathlib import Path
import sys

def check_integrity(exam_dir):
    """检查所有已处理页面的完整性"""
    exam_dir = Path(exam_dir)

    # 统计所有page文件
    all_pages = sorted(exam_dir.glob("page_*.png"))
    total_pages = len(all_pages)

    print(f"总页数: {total_pages}")
    print(f"\n{'='*80}")
    print(f"{'页码':<10} {'状态':<8} {'题目数':<8} {'图片数':<8} {'说明'}")
    print(f"{'='*80}")

    issues = []
    processed_count = 0
    total_questions = 0

    for page_img in all_pages:
        page_num = page_img.stem.replace("page_", "")
        questions_dir = exam_dir / f"questions_{page_img.stem}"
        meta_file = questions_dir / "meta.json"

        if not meta_file.exists():
            print(f"{page_num:<10} {'未处理':<8} {'-':<8} {'-':<8} 缺少meta.json")
            issues.append(f"page_{page_num}: 未处理")
            continue

        # 读取meta.json
        try:
            with meta_file.open("r", encoding="utf-8") as f:
                data = json.load(f)
        except json.JSONDecodeError as e:
            print(f"{page_num:<10} {'损坏':<8} {'-':<8} {'-':<8} JSON格式错误: {e}")
            issues.append(f"page_{page_num}: meta.json损坏")
            continue
        except Exception as e:
            print(f"{page_num:<10} {'错误':<8} {'-':<8} {'-':<8} 读取失败: {e}")
            issues.append(f"page_{page_num}: 读取失败")
            continue

        # 检查题目数量
        questions = data.get("questions", [])
        q_count = len(questions)

        # 检查实际图片文件
        img_files = list(questions_dir.glob("q*.png"))
        img_count = len(img_files)

        # 验证完整性
        status = "✓"
        note = ""

        if q_count == 0:
            status = "✓"  # 空页也是正常处理完成的
            note = "空页（无题目）"
            # 不再添加到issues列表
        elif img_count < q_count:
            status = "⚠"
            note = f"缺少图片文件 (应有{q_count}张)"
            issues.append(f"page_{page_num}: 缺少图片")
        elif img_count > q_count * 2:  # 考虑跨页情况，最多2倍
            status = "⚠"
            note = "图片数量异常"
            issues.append(f"page_{page_num}: 图片数量异常")

        # 检查题号连续性（可选）
        qnos = [q.get("qno") for q in questions if q.get("qno")]
        if qnos:
            qno_range = f"Q{min(qnos)}-Q{max(qnos)}"
            if not note:
                note = qno_range

        print(f"{page_num:<10} {status:<8} {q_count:<8} {img_count:<8} {note}")

        processed_count += 1
        total_questions += q_count

    # 总结
    print(f"{'='*80}")
    print(f"\n总结:")
    print(f"  - 总页数: {total_pages}")
    print(f"  - 已处理: {processed_count} 页")
    print(f"  - 未处理: {total_pages - processed_count} 页")
    print(f"  - 总题数: {total_questions} 题")

    if issues:
        print(f"\n发现 {len(issues)} 个问题:")
        for issue in issues:
            print(f"  ⚠ {issue}")
        return False
    else:
        print("\n✓ 所有已处理页面完整性验证通过")
        return True

if __name__ == "__main__":
    if len(sys.argv) > 1:
        exam_dir = sys.argv[1]
    else:
        # 使用.last_processed
        last_file = Path("pdf_images/.last_processed")
        if last_file.exists():
            exam_name = last_file.read_text(encoding="utf-8").strip()
            exam_dir = Path("pdf_images") / exam_name
        else:
            print("错误: 请指定试卷目录")
            sys.exit(1)

    success = check_integrity(exam_dir)
    sys.exit(0 if success else 1)
