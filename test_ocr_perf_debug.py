#!/usr/bin/env python3
"""OCR 性能测试脚本 - 增强版（带详细性能日志）"""
import os
import sys
import time
import json
from pathlib import Path

# 设置环境变量 - 开启性能追踪
os.environ.setdefault("EXAMPAPER_USE_GPU", "1")
os.environ.setdefault("EXAMPAPER_PARALLEL_EXTRACTION", "1")
os.environ.setdefault("EXAMPAPER_DET_BATCH_SIZE", "4")
os.environ.setdefault("EXAMPAPER_REC_BATCH_SIZE", "32")
os.environ.setdefault("EXAMPAPER_PREFETCH_SIZE", "8")
os.environ.setdefault("EXAMPAPER_MAX_WORKERS", "2")
os.environ.setdefault("EXAMPAPER_GPU_CONCURRENCY", "1")

# 🔥 关键：开启性能日志
os.environ["EXAMPAPER_PERF_LOG"] = "1"
os.environ["EXAMPAPER_PERF_TRACE"] = "perf_trace.jsonl"

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
    print("  OCR 性能测试 (DEBUG 模式)")
    print("=" * 60)
    print(f"  测试图片: {len(img_paths)} 张")
    print(f"  DET_BATCH_SIZE: {os.getenv('EXAMPAPER_DET_BATCH_SIZE')}")
    print(f"  REC_BATCH_SIZE: {os.getenv('EXAMPAPER_REC_BATCH_SIZE')}")
    print(f"  PREFETCH_SIZE: {os.getenv('EXAMPAPER_PREFETCH_SIZE')}")
    print(f"  MAX_WORKERS: {os.getenv('EXAMPAPER_MAX_WORKERS')}")
    print(f"  GPU_CONCURRENCY: {os.getenv('EXAMPAPER_GPU_CONCURRENCY')}")
    print(f"  性能追踪: {os.getenv('EXAMPAPER_PERF_TRACE')}")
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
        t_now = time.strftime("%H:%M:%S")
        print(f"  [{done}/{total}] {t_now} - {page}: {status}")

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

    # 分析性能日志
    print("\n[分析] 正在分析性能瓶颈...")
    analyze_perf_trace()


def analyze_perf_trace():
    """分析性能追踪日志并生成诊断报告"""
    trace_file = Path("perf_trace.jsonl")
    if not trace_file.exists():
        print("  ⚠️ 性能追踪文件不存在")
        return

    # 读取所有事件
    events = []
    with trace_file.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    pass

    if not events:
        print("  ⚠️ 未找到性能事件")
        return

    # 按页面分组分析
    ocr_predict_events = [e for e in events if e.get("event") == "ocr.predict"]
    page_done_events = [e for e in events if e.get("event") == "page.done"]

    if not ocr_predict_events:
        print("  ⚠️ 未找到 ocr.predict 事件")
        return

    print(f"\n  ✓ 找到 {len(ocr_predict_events)} 条 ocr.predict 记录")
    print(f"  ✓ 找到 {len(page_done_events)} 条 page.done 记录")

    # 统计GPU锁等待时间 vs 真实推理时间
    total_gpu_wait = sum(e.get("gpu_lock_wait_ms", 0) for e in ocr_predict_events)
    total_predict = sum(e.get("predict_ms", 0) for e in ocr_predict_events)
    avg_gpu_wait = total_gpu_wait / len(ocr_predict_events) if ocr_predict_events else 0
    avg_predict = total_predict / len(ocr_predict_events) if ocr_predict_events else 0

    print("\n  【GPU锁 vs 推理时间】")
    print(f"    平均等GPU锁: {avg_gpu_wait:.0f}ms")
    print(f"    平均推理时间: {avg_predict:.0f}ms")
    print(f"    等待比例: {100 * avg_gpu_wait / (avg_gpu_wait + avg_predict):.1f}%")

    # 找出最慢的3个页面
    page_timings = {}
    for e in page_done_events:
        page = e.get("page")
        total_ms = e.get("total_ms", 0)
        queue_wait_ms = e.get("queue_wait_ms", 0)
        if page:
            page_timings[page] = {"total_ms": total_ms, "queue_wait_ms": queue_wait_ms}

    # 关联OCR事件
    for e in ocr_predict_events:
        page = e.get("page")
        if page and page in page_timings:
            page_timings[page]["gpu_wait_ms"] = e.get("gpu_lock_wait_ms", 0)
            page_timings[page]["predict_ms"] = e.get("predict_ms", 0)

    if page_timings:
        print("\n  【最慢的3个页面】")
        sorted_pages = sorted(page_timings.items(), key=lambda x: x[1].get("total_ms", 0), reverse=True)
        for page, timing in sorted_pages[:3]:
            print(f"\n    {page}:")
            print(f"      总耗时: {timing.get('total_ms', 0):.0f}ms")
            print(f"      队列等待: {timing.get('queue_wait_ms', 0):.0f}ms")
            print(f"      GPU锁等待: {timing.get('gpu_wait_ms', 0):.0f}ms")
            print(f"      推理时间: {timing.get('predict_ms', 0):.0f}ms")

    # 诊断结论
    print("\n  【诊断结论】")
    if avg_gpu_wait > avg_predict * 2:
        print("    ⚠️ GPU锁等待时间过长 (是推理时间的2倍以上)")
        print("    💡 建议: 增加 EXAMPAPER_GPU_CONCURRENCY=2 (如果显存充足)")
    elif avg_predict > 5000:
        print("    ⚠️ 推理时间过长 (>5秒/页)")
        print("    💡 建议: 检查GPU是否正常工作 (运行 nvidia-smi 确认)")
    else:
        print("    ✓ GPU利用率正常")

    # 检查是否有显著的队列等待
    avg_queue_wait = sum(e.get("queue_wait_ms", 0) for e in page_done_events) / len(page_done_events) if page_done_events else 0
    if avg_queue_wait > 1000:
        print(f"    ⚠️ 队列等待时间较长 (平均{avg_queue_wait:.0f}ms)")
        print("    💡 建议: 增加 EXAMPAPER_PREFETCH_SIZE 或检查磁盘I/O")


if __name__ == "__main__":
    main()
