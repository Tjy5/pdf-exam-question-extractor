#!/usr/bin/env python3
"""OCR 性能测试脚本"""
import os
import sys
import time
from pathlib import Path

# 设置环境变量
os.environ.setdefault("EXAMPAPER_USE_GPU", "1")
os.environ.setdefault("EXAMPAPER_PARALLEL_EXTRACTION", "1")
os.environ.setdefault("EXAMPAPER_DET_BATCH_SIZE", "2")
os.environ.setdefault("EXAMPAPER_REC_BATCH_SIZE", "16")
os.environ.setdefault("EXAMPAPER_PREFETCH_SIZE", "8")
os.environ.setdefault("EXAMPAPER_MAX_WORKERS", "4")

from backend.src.common.ocr_models import get_ppstructure, warmup_ppstructure
from backend.src.services.parallel_extraction import ParallelPageProcessor
from backend.src.services.pipeline.impl.extract_questions import (
    extract_questions_from_page,
    save_questions_for_page,
)


def is_valid_meta(meta_path: Path) -> bool:
    """检查 meta.json 是否有效"""
    return meta_path.exists() and meta_path.stat().st_size > 10


def main():
    # 测试图片路径
    test_dir = Path("pdf_images/测试")
    img_paths = sorted(test_dir.glob("*.png"))

    if not img_paths:
        print("[ERROR] 未找到测试图片")
        sys.exit(1)

    print("=" * 60)
    print("  OCR 性能测试")
    print("=" * 60)
    print(f"  测试图片: {len(img_paths)} 张")
    print(f"  DET_BATCH_SIZE: {os.getenv('EXAMPAPER_DET_BATCH_SIZE')}")
    print(f"  REC_BATCH_SIZE: {os.getenv('EXAMPAPER_REC_BATCH_SIZE')}")
    print(f"  PREFETCH_SIZE: {os.getenv('EXAMPAPER_PREFETCH_SIZE')}")
    print(f"  MAX_WORKERS: {os.getenv('EXAMPAPER_MAX_WORKERS')}")
    print("=" * 60)

    # 初始化模型
    print("\n[1/3] 初始化 PP-StructureV3 模型...")
    t0 = time.perf_counter()
    pipeline = get_ppstructure()
    init_time = time.perf_counter() - t0
    print(f"  模型初始化耗时: {init_time:.2f}s")

    # Warmup
    print("\n[2/3] 模型预热...")
    t0 = time.perf_counter()
    warmup_ppstructure()
    warmup_time = time.perf_counter() - t0
    print(f"  预热耗时: {warmup_time:.2f}s")

    # 输出目录
    output_dir = Path("test_output")
    output_dir.mkdir(exist_ok=True)

    # 创建处理器
    processor = ParallelPageProcessor(
        max_workers=int(os.getenv("EXAMPAPER_MAX_WORKERS", "4")),
        pipeline=pipeline,
    )
    processor.set_extraction_functions(
        extract_fn=extract_questions_from_page,
        save_fn=save_questions_for_page,
        is_valid_meta_fn=is_valid_meta,
    )

    # 处理进度回调
    def progress_cb(done: int, total: int, status: str, page: str):
        print(f"  [{done}/{total}] {page}: {status}")

    # 执行处理
    print(f"\n[3/3] 并行处理 {len(img_paths)} 张图片...")
    t0 = time.perf_counter()
    results = processor.process_pages_parallel(
        img_paths=img_paths,
        base_output_dir=output_dir,
        skip_existing=False,
        progress_callback=progress_cb,
        log=lambda m: print(f"  {m}"),
    )
    process_time = time.perf_counter() - t0

    # 统计结果
    success = sum(1 for r in results if r.get("status") == "success")
    errors = sum(1 for r in results if r.get("status") == "error")
    total_questions = sum(r.get("question_count", 0) for r in results)

    print("\n" + "=" * 60)
    print("  测试结果")
    print("=" * 60)
    print(f"  处理耗时: {process_time:.2f}s")
    print(f"  平均每页: {process_time / len(img_paths):.2f}s")
    print(f"  吞吐量: {len(img_paths) / process_time:.2f} 页/秒")
    print(f"  成功: {success}, 错误: {errors}")
    print(f"  检测到题目: {total_questions} 道")
    print("=" * 60)


if __name__ == "__main__":
    main()
