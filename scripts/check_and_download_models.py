"""
检查和下载 PaddleOCR 模型

用于诊断模型加载问题，并预下载所有需要的模型。
"""

import os
import sys
from pathlib import Path

# 添加项目根目录到路径
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def check_model_cache():
    """检查本地模型缓存"""
    print("=" * 60)
    print("1. 检查本地模型缓存")
    print("=" * 60)
    print()

    # 检查可能的缓存位置
    cache_locations = [
        Path.home() / ".paddlex" / "official_models",
        Path.home() / ".paddleocr",
        Path.home() / ".cache" / "paddle",
    ]

    found_any = False
    for loc in cache_locations:
        if loc.exists():
            print(f"[FOUND] {loc}")

            # 列出子目录和大小
            try:
                for item in loc.iterdir():
                    if item.is_dir():
                        size = sum(f.stat().st_size for f in item.rglob("*") if f.is_file())
                        size_mb = size / (1024 * 1024)
                        print(f"  - {item.name}: {size_mb:.1f} MB")
                found_any = True
            except Exception as e:
                print(f"  (Cannot read: {e})")
        else:
            print(f"[NOT FOUND] {loc}")

    print()
    if not found_any:
        print("[WARNING] No model cache found locally!")
        print("          First run will download models from internet (may take several minutes)")

    print()
    return found_any


def list_required_models():
    """列出项目需要的模型"""
    print("=" * 60)
    print("2. 项目使用的模型配置")
    print("=" * 60)
    print()

    print("根据 src/common/ocr_models.py 的配置:")
    print()
    print("PP-StructureV3 sub-models:")
    print("  [ENABLED] Layout Analysis")
    print("  [ENABLED] OCR (Text Recognition)")
    print("  [ENABLED] Table Recognition (can disable with EXAMPAPER_LIGHT_TABLE=1)")
    print("  [DISABLED] Document Orientation Classification")
    print("  [DISABLED] Document Unwarping")
    print("  [DISABLED] Formula Recognition")
    print("  [DISABLED] Chart Recognition")
    print("  [DISABLED] Seal Recognition")
    print()


def test_model_loading():
    """测试模型加载"""
    print("=" * 60)
    print("3. 测试模型加载（这会触发首次下载）")
    print("=" * 60)
    print()

    try:
        import time
        print("正在加载 PP-StructureV3...")
        print("(首次运行可能需要下载模型，请耐心等待)")
        print()

        start = time.time()

        from src.common.ocr_models import get_ppstructure

        pipeline = get_ppstructure()

        elapsed = time.time() - start

        print(f"[SUCCESS] Model loaded! Time: {elapsed:.2f} seconds")
        print()

        # 测试预热
        print("Testing model warmup...")
        start = time.time()

        from src.common.ocr_models import warmup_ppstructure
        warmup_ppstructure()

        elapsed = time.time() - start
        print(f"[SUCCESS] Warmup complete! Time: {elapsed:.2f} seconds")
        print()

        return True

    except Exception as e:
        print(f"[ERROR] Model loading failed: {e}")
        print()
        import traceback
        traceback.print_exc()
        return False


def main():
    """主函数"""
    print()
    print("=" * 60)
    print("    PaddleOCR Model Check & Download Tool")
    print("=" * 60)
    print()

    # 1. 检查缓存
    has_cache = check_model_cache()

    # 2. 列出需要的模型
    list_required_models()

    # 3. 询问是否测试加载
    if not has_cache:
        print("[WARNING] No local model cache detected")
        print()
        response = input("Download and test models now? (y/n): ").strip().lower()
        if response == 'y':
            success = test_model_loading()
            if success:
                print()
                print("=" * 60)
                print("[SUCCESS] All checks passed! Models are ready")
                print("=" * 60)
            else:
                print()
                print("=" * 60)
                print("[ERROR] Model loading failed, check network and dependencies")
                print("=" * 60)
        else:
            print()
            print("Skipped model download.")
            print("Note: Models will be auto-downloaded on first Web service startup.")
    else:
        print("[OK] Local model cache found, ready to use")
        print()
        response = input("Test model loading speed? (y/n): ").strip().lower()
        if response == 'y':
            test_model_loading()


if __name__ == "__main__":
    main()
