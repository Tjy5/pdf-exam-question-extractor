"""
GPU 性能对比测试

比较 CPU 和 GPU 模式下的模型加载和推理速度
"""

import os
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))


def test_model_loading(use_gpu: bool, test_name: str):
    """测试模型加载和推理性能"""
    print(f"\n{'=' * 60}")
    print(f"  {test_name}")
    print(f"{'=' * 60}\n")

    # 设置环境变量
    os.environ["EXAMPAPER_USE_GPU"] = "1" if use_gpu else "0"

    # 清除缓存，确保公平测试
    from src.common.ocr_models import reset_ppstructure_cache
    reset_ppstructure_cache()

    # 测试 1: 模型加载时间
    print("[Test 1] Model Loading Time")
    start = time.time()

    from src.common.ocr_models import get_ppstructure
    pipeline = get_ppstructure()

    load_time = time.time() - start
    print(f"  Load time: {load_time:.2f}s")

    # 测试 2: 预热时间
    print("\n[Test 2] Warmup Time (first inference)")
    start = time.time()

    from src.common.ocr_models import warmup_ppstructure
    warmup_ppstructure()

    warmup_time = time.time() - start
    print(f"  Warmup time: {warmup_time:.2f}s")

    # 测试 3: 实际页面推理（如果有测试图片）
    test_image = PROJECT_ROOT / "docs" / "test_page.png"
    if test_image.exists():
        print("\n[Test 3] Real Page Inference")
        start = time.time()

        result = pipeline.predict(str(test_image))

        inference_time = time.time() - start
        print(f"  Inference time: {inference_time:.2f}s")
    else:
        print("\n[Test 3] Real Page Inference - SKIPPED (no test image)")
        inference_time = None

    print(f"\n{'=' * 60}")
    print("Summary:")
    print(f"  Total time: {load_time + warmup_time:.2f}s")
    if inference_time:
        print(f"  (including real inference: {load_time + warmup_time + inference_time:.2f}s)")
    print(f"{'=' * 60}\n")

    return {
        "load_time": load_time,
        "warmup_time": warmup_time,
        "inference_time": inference_time,
        "total_time": load_time + warmup_time,
    }


def main():
    print("\n" + "=" * 60)
    print("    GPU Performance Benchmark")
    print("=" * 60)

    # 测试 CPU 模式
    cpu_results = test_model_loading(False, "CPU Mode")

    # 测试 GPU 模式
    gpu_results = test_model_loading(True, "GPU Mode")

    # 对比结果
    print("\n" + "=" * 60)
    print("    Performance Comparison")
    print("=" * 60)
    print()

    print(f"{'Metric':<25} {'CPU':<12} {'GPU':<12} {'Speedup':<12}")
    print("-" * 60)

    metrics = [
        ("Model Loading", "load_time"),
        ("Warmup (1st inference)", "warmup_time"),
        ("Total", "total_time"),
    ]

    for name, key in metrics:
        cpu_val = cpu_results[key]
        gpu_val = gpu_results[key]
        speedup = cpu_val / gpu_val if gpu_val > 0 else 0

        print(
            f"{name:<25} {cpu_val:>10.2f}s {gpu_val:>10.2f}s {speedup:>10.2f}x"
        )

    if cpu_results["inference_time"] and gpu_results["inference_time"]:
        cpu_val = cpu_results["inference_time"]
        gpu_val = gpu_results["inference_time"]
        speedup = cpu_val / gpu_val

        print(
            f"{'Real Inference':<25} {cpu_val:>10.2f}s {gpu_val:>10.2f}s {speedup:>10.2f}x"
        )

    print("\n" + "=" * 60)
    print("[CONCLUSION]")

    total_speedup = cpu_results["total_time"] / gpu_results["total_time"]
    if total_speedup > 1.5:
        print(f"  GPU provides {total_speedup:.1f}x speedup - SIGNIFICANT!")
    elif total_speedup > 1.1:
        print(f"  GPU provides {total_speedup:.1f}x speedup - Moderate")
    else:
        print(f"  GPU speedup is minimal ({total_speedup:.1f}x)")
        print("  Note: Model loading is I/O bound, GPU mainly accelerates inference")

    print("=" * 60 + "\n")


if __name__ == "__main__":
    main()
