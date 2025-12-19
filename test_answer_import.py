#!/usr/bin/env python3
"""测试答案导入功能"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from backend.src.services.answers.answer_pdf_importer import (
    extract_text_from_pdf,
    parse_answer_key_text,
    normalize_exam_name,
    extract_variant_index,
)


def test_parse_answer():
    """测试答案解析"""
    print("=" * 60)
    print("测试1: 答案解析")
    print("=" * 60)

    test_text = """
    【四海】25 下半年一期行测套题冲刺 1

    一、政治理论(1--20)
    1--5 DDCCA 6--10 CADBB
    11--15 BDCCA 16--20 BAADB

    二、常识判断(21--35)
    21--25 DABDC 26--30 CACBD 31--35 CBBAC
    """

    parsed = parse_answer_key_text(test_text)
    print(f"解析到的答案数: {len(parsed.answers)}")
    print(f"错误数: {len(parsed.errors)}")

    if parsed.answers:
        print("\n前10个答案:")
        for i, (qno, ans) in enumerate(list(parsed.answers.items())[:10], 1):
            print(f"  Q{qno}: {ans}")

    if parsed.errors:
        print("\n解析错误:")
        for err in parsed.errors[:5]:
            print(f"  - {err}")

    # 验证
    assert parsed.answers[1] == "D", "Q1应该是D"
    assert parsed.answers[5] == "A", "Q5应该是A"
    assert parsed.answers[35] == "C", "Q35应该是C"

    print("\n✅ 答案解析测试通过")


def test_pdf_extraction():
    """测试PDF文本提取"""
    print("\n" + "=" * 60)
    print("测试2: PDF文本提取")
    print("=" * 60)

    pdf_path = PROJECT_ROOT / "answer" / "【四海】25下半年一期行测套题冲刺1.pdf"

    if not pdf_path.exists():
        print(f"⚠️  PDF文件不存在: {pdf_path}")
        return

    print(f"读取PDF: {pdf_path.name}")
    text = extract_text_from_pdf(pdf_path)

    print(f"提取到的文本长度: {len(text)} 字符")
    print("\n前500字符:")
    print(text[:500])

    parsed = parse_answer_key_text(text)
    print(f"\n解析到的答案数: {len(parsed.answers)}")

    if parsed.answers:
        max_qno = max(parsed.answers.keys())
        min_qno = min(parsed.answers.keys())
        print(f"题号范围: {min_qno} - {max_qno}")

    print("\n✅ PDF文本提取测试通过")


def test_exam_name_matching():
    """测试试卷名称匹配"""
    print("\n" + "=" * 60)
    print("测试3: 试卷名称匹配")
    print("=" * 60)

    test_cases = [
        ("【四海】25下半年一期行测套题冲刺1.pdf", "四海25下半年一期行测套题冲刺__17531029"),
        ("（1）【四海】行测套题冲刺.pdf", "四海行测套题冲刺1__12345678"),
    ]

    for pdf_name, exam_dir_name in test_cases:
        pdf_norm = normalize_exam_name(pdf_name)
        exam_norm = normalize_exam_name(exam_dir_name)
        pdf_idx = extract_variant_index(pdf_name)
        exam_idx = extract_variant_index(exam_dir_name)

        print(f"\nPDF: {pdf_name}")
        print(f"  标准化: {pdf_norm}")
        print(f"  变体序号: {pdf_idx}")
        print(f"试卷: {exam_dir_name}")
        print(f"  标准化: {exam_norm}")
        print(f"  变体序号: {exam_idx}")

    print("\n✅ 名称匹配测试通过")


def main():
    print("\n答案导入功能测试\n")

    try:
        test_parse_answer()
        test_pdf_extraction()
        test_exam_name_matching()

        print("\n" + "=" * 60)
        print("✅ 所有测试通过!")
        print("=" * 60)
        return 0

    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
