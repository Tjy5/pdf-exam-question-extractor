#!/usr/bin/env python3
"""通过API手动指定试卷ID导入答案"""

import requests
from pathlib import Path

# 配置
API_BASE = "http://localhost:8000"
ANSWER_DIR = Path("answer")

# PDF文件与试卷ID的映射（根据你的需求调整）
MAPPINGS = {
    "【四海】25下半年一期行测套题冲刺1.pdf": 3,  # （1）【四海】25下半年1期套题班《行测》
    "【四海】25下半年一期行测套题冲刺2.pdf": 4,  # （2）【四海】25下半年1期套题班《行测》
    "【四海】25下半年一期行测套题冲刺3.pdf": 7,  # （3）【四海】25下半年1期套题班《行测》
    "【四海】25下半年一期行测套题冲刺4.pdf": 5,  # （4）【四海】25下半年1期套题班《行测》
    "【四海】25下半年一期行测套题冲刺5.pdf": 6,  # （5）【四海】25下半年1期套题班《行测》
}


def import_answer_for_exam(pdf_filename: str, exam_id: int):
    """为指定试卷导入答案"""
    pdf_path = ANSWER_DIR / pdf_filename

    if not pdf_path.exists():
        print(f"  ❌ 文件不存在: {pdf_filename}")
        return False

    print(f"\n上传: {pdf_filename} → 试卷ID={exam_id}")

    # 构建multipart/form-data请求
    url = f"{API_BASE}/api/exams/{exam_id}/answers:import"

    with open(pdf_path, "rb") as f:
        files = {
            "file": (pdf_filename, f, "application/pdf")
        }
        data = {
            "source": "pdf_manual"
        }

        try:
            response = requests.post(url, files=files, data=data, timeout=60)

            if response.status_code == 200:
                result = response.json()
                print(f"  ✅ 成功导入 {result['imported']} 个答案")
                if result['skipped'] > 0:
                    print(f"  ⚠️  跳过 {result['skipped']} 个")
                if result.get('errors'):
                    print(f"  ⚠️  {len(result['errors'])} 个错误:")
                    for err in result['errors'][:3]:
                        print(f"       - {err}")
                return True
            else:
                print(f"  ❌ 失败 (HTTP {response.status_code}): {response.text}")
                return False

        except Exception as e:
            print(f"  ❌ 错误: {e}")
            return False


def main():
    print("=" * 60)
    print("手动指定试卷ID导入答案")
    print("=" * 60)

    print("\n映射关系:")
    for pdf_name, exam_id in MAPPINGS.items():
        print(f"  {pdf_name} → 试卷{exam_id}")

    print("\n开始导入...")

    success_count = 0
    for pdf_filename, exam_id in MAPPINGS.items():
        if import_answer_for_exam(pdf_filename, exam_id):
            success_count += 1

    print("\n" + "=" * 60)
    print(f"✅ 完成! 成功导入 {success_count}/{len(MAPPINGS)} 个文件")
    print("=" * 60)


if __name__ == "__main__":
    main()
