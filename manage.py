#!/usr/bin/env python3
"""
manage.py - 项目统一管理入口

使用方法：
    python manage.py                    # 启动Web服务器（默认，GPU优化已内置）
    python manage.py web                # 启动Web服务器
    python manage.py web --port 9000    # 在指定端口启动Web服务器
    python manage.py web --no-gpu       # 禁用GPU加速
    python manage.py web --workers 8    # 设置并行工作线程数
"""

import os
import sys
import socket
import argparse
import subprocess
from pathlib import Path
from typing import Any, Dict, Optional


# =============================================================================
# Environment Configuration (from start_web_production.bat)
# =============================================================================

DEFAULT_ENV_CONFIG = {
    # GPU Acceleration
    "EXAMPAPER_USE_GPU": "1",
    # GPU Memory Limit (60% for stability, prevents hang/OOM on small GPUs)
    "FLAGS_fraction_of_gpu_memory_to_use": "0.6",
    # PaddlePaddle GPU Performance Optimization
    "FLAGS_allocator_strategy": "auto_growth",
    "FLAGS_cudnn_deterministic": "0",
    "FLAGS_cudnn_batchnorm_spatial_persistent": "1",
    "FLAGS_conv_workspace_size_limit": "4096",
    # In-process execution (avoid reloading models)
    "EXAMPAPER_STEP1_INPROC": "1",
    "EXAMPAPER_STEP2_INPROC": "1",
    # Model warmup (preload on startup)
    "EXAMPAPER_PPSTRUCTURE_WARMUP": "1",
    # Web stability: bind PPStructure predict() to a dedicated OS thread.
    # Helps avoid rare Paddle/CUDA thread-affinity hangs in async + high-worker setups.
    "EXAMPAPER_PPSTRUCTURE_THREAD_BOUND_PREDICT": "1",
    # Async warmup (server starts immediately, model loads in background)
    # DISABLED: Async warmup can cause first page to hang waiting for model
    "EXAMPAPER_PPSTRUCTURE_WARMUP_ASYNC": "0",
    # Fallback to subprocess if in-proc fails
    "EXAMPAPER_STEP1_FALLBACK_SUBPROCESS": "1",
    "EXAMPAPER_STEP2_FALLBACK_SUBPROCESS": "1",
    # Table recognition (keep enabled for data analysis)
    "EXAMPAPER_LIGHT_TABLE": "0",
    # Note: OCR batch sizes (DET_BATCH_SIZE, REC_BATCH_SIZE), PREFETCH_SIZE, and MAX_WORKERS
    # are auto-calculated based on hardware in calculate_optimal_params()
    # Parallel extraction
    "EXAMPAPER_PARALLEL_EXTRACTION": "1",
    # GPU lock timeout (seconds) - prevent infinite hangs
    "EXAMPAPER_GPU_LOCK_TIMEOUT_S": "120",
    # OCR predict warning threshold (seconds)
    "EXAMPAPER_OCR_PREDICT_WARN_AFTER_S": "60",
}


def detect_gpu_available() -> bool:
    """Check if NVIDIA GPU is available via nvidia-smi"""
    try:
        result = subprocess.run(
            ["nvidia-smi"], capture_output=True, timeout=5
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired, PermissionError, OSError):
        return False


def detect_hardware() -> Dict[str, Any]:
    """
    Detect hardware info for auto-tuning.

    Returns:
        {"gpu_available": bool, "gpu_vram_gb": int, "gpu_name": str|None,
         "ram_gb": int|None, "cpu_cores": int|None}
    """
    hw: Dict[str, Any] = {
        "gpu_available": False,
        "gpu_vram_gb": 0,
        "gpu_name": None,
        "ram_gb": None,
        "cpu_cores": os.cpu_count(),
    }

    # GPU VRAM (first GPU)
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.total,name", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0 and result.stdout:
            first_line = result.stdout.splitlines()[0]
            mem_str, *name_parts = first_line.split(",")
            hw["gpu_vram_gb"] = int(mem_str.strip()) // 1024
            hw["gpu_name"] = ",".join(name_parts).strip() or None
            hw["gpu_available"] = hw["gpu_vram_gb"] > 0
    except (FileNotFoundError, subprocess.TimeoutExpired, ValueError, PermissionError, OSError):
        hw["gpu_available"] = False

    # RAM
    try:
        import psutil
        hw["ram_gb"] = int(psutil.virtual_memory().total / (1024**3))
    except Exception:
        hw["ram_gb"] = None

    return hw


def calculate_optimal_params(hw: Dict[str, Any]) -> Dict[str, str]:
    """
    Derive conservative env defaults based on detected hardware.

    Design goal: stability > throughput.
    - Treat 6GB and below as "small VRAM" and use extremely conservative settings.
    - Cap workers to <=4 for all machines to reduce long-run GPU/driver instability.
    - Use lower GPU memory fraction (0.6) by default to reduce fragmentation/OOM-like hangs.
    """
    vram = int(hw.get("gpu_vram_gb") or 0)
    ram = int(hw.get("ram_gb") or 0)
    cores = int(hw.get("cpu_cores") or 4)

    # Always default to a safer GPU memory fraction for stability
    gpu_mem_fraction = 0.6

    # Conservative batch sizes by VRAM tier
    # NOTE: For PP-StructureV3 on laptop-class GPUs, stability issues often show up as long hangs
    # rather than clean OOM exceptions, so we bias toward smaller batches.
    if vram <= 6:
        det_bs, rec_bs = 1, 8
    elif vram <= 8:
        det_bs, rec_bs = 1, 12
    elif vram <= 12:
        det_bs, rec_bs = 2, 16
    else:
        det_bs, rec_bs = 2, 24

    # Conservative prefetch sizing (reduce IO/cache pressure + overall memory churn)
    # Special-case small VRAM GPUs: keep prefetch minimal.
    if vram <= 6:
        prefetch = 2
    else:
        if ram >= 32:
            prefetch = 6
        elif ram >= 16:
            prefetch = 4
        else:
            prefetch = 2

    # Conservative worker sizing:
    # - Small VRAM: hard cap at 2 (GPU is bottleneck; more workers adds pressure/churn)
    # - Others: scale gently, but cap at 4 always
    if vram <= 6:
        workers = 2
    else:
        if cores >= 16:
            workers = 4
        elif cores >= 8:
            workers = 3
        else:
            workers = 2

    workers = max(1, min(4, workers))

    return {
        "FLAGS_fraction_of_gpu_memory_to_use": str(gpu_mem_fraction),
        "EXAMPAPER_DET_BATCH_SIZE": str(det_bs),
        "EXAMPAPER_REC_BATCH_SIZE": str(rec_bs),
        "EXAMPAPER_PREFETCH_SIZE": str(prefetch),
        "EXAMPAPER_MAX_WORKERS": str(workers),
    }


def setup_environment(
    use_gpu: bool = True,
    workers: int = 4,
    warmup: bool = True,
    hardware: Optional[Dict[str, Any]] = None,
):
    """Setup environment variables for optimal performance"""
    for key, value in DEFAULT_ENV_CONFIG.items():
        os.environ.setdefault(key, value)

    # Auto-detect hardware and apply calculated defaults (env/CLI still override)
    if hardware is None:
        hardware = detect_hardware()
    auto_env = calculate_optimal_params(hardware)
    for key, value in auto_env.items():
        os.environ.setdefault(key, value)

    # Override based on CLI arguments
    if not use_gpu:
        os.environ["EXAMPAPER_USE_GPU"] = "0"
    if workers != 4:
        os.environ["EXAMPAPER_MAX_WORKERS"] = str(workers)
    if not warmup:
        os.environ["EXAMPAPER_PPSTRUCTURE_WARMUP"] = "0"
        os.environ["EXAMPAPER_PPSTRUCTURE_WARMUP_ASYNC"] = "0"


def is_port_in_use(port: int) -> int | None:
    """Check if port is in use, return PID if found (Windows only)"""
    if sys.platform != "win32":
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            return None if s.connect_ex(("127.0.0.1", port)) != 0 else -1

    try:
        result = subprocess.run(
            ["netstat", "-ano"],
            capture_output=True, text=True, timeout=10, encoding="gbk", errors="ignore"
        )
        if not result.stdout:
            return None
        for line in result.stdout.splitlines():
            parts = line.split()
            # netstat output: Proto LocalAddress ForeignAddress State PID
            if len(parts) >= 5 and parts[3].upper() == "LISTENING":
                try:
                    local_port = int(parts[1].rsplit(":", 1)[-1])
                except ValueError:
                    continue
                if local_port == port:
                    return int(parts[-1])
    except (subprocess.TimeoutExpired, ValueError, PermissionError, OSError):
        pass
    return None


def kill_process(pid: int) -> bool:
    """Kill process by PID"""
    try:
        cmd = (
            ["taskkill", "/F", "/PID", str(pid)]
            if sys.platform == "win32"
            else ["kill", "-9", str(pid)]
        )
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        if result.returncode != 0:
            error_msg = (result.stderr or result.stdout or "").strip()
            if error_msg:
                print(f"  [ERROR] Failed to kill PID {pid}: {error_msg}")
            return False
        return True
    except subprocess.TimeoutExpired:
        print(f"  [ERROR] Killing PID {pid} timed out")
        return False


def cleanup_port(port: int) -> bool:
    """Clean up processes using the specified port"""
    pid = is_port_in_use(port)
    if pid is None:
        return True
    if pid == -1:
        print(f"  [WARN] Port {port} is in use (non-Windows, cannot auto-kill)")
        return False

    print(f"  [WARN] Port {port} is used by PID {pid}")
    print(f"  [Cleanup] Killing old process...")
    if kill_process(pid):
        print(f"  [OK] Old process terminated")
        import time
        time.sleep(1)
        return True
    else:
        print(f"  [ERROR] Failed to kill process (admin rights may be required)")
        return False


def print_config_summary(
    use_gpu: bool,
    workers: int,
    warmup: bool,
    gpu_detected: bool = True,
    hardware: Optional[Dict[str, Any]] = None,
):
    """Print configuration summary"""
    print("=" * 50)
    print("  Configuration")
    print("=" * 50)
    if use_gpu:
        gpu_status = "ENABLED"
    elif not gpu_detected:
        gpu_status = "DISABLED (GPU not detected)"
    else:
        gpu_status = "DISABLED"
    print(f"  GPU Acceleration: {gpu_status}")
    if hardware:
        gpu_name = hardware.get("gpu_name")
        vram = hardware.get("gpu_vram_gb", 0)
        if gpu_name:
            print(f"  GPU: {gpu_name} ({vram} GB)")
        elif vram:
            print(f"  GPU VRAM: {vram} GB")
        ram = hardware.get("ram_gb")
        if ram:
            print(f"  RAM: {ram} GB")
        cores = hardware.get("cpu_cores")
        if cores:
            print(f"  CPU Cores: {cores}")
    print(f"  Parallel Workers: {os.getenv('EXAMPAPER_MAX_WORKERS', workers)}")
    print(f"  Model Warmup: {'ENABLED' if warmup else 'DISABLED'}")
    print(f"  In-process Execution: ENABLED")
    print(f"  Subprocess Fallback: ENABLED")
    print(
        f"  GPU Memory Fraction: {os.getenv('FLAGS_fraction_of_gpu_memory_to_use', '0.6')}"
    )
    print(
        f"  Auto Params (stability-optimized): "
        f"det_batch={os.getenv('EXAMPAPER_DET_BATCH_SIZE')}, "
        f"rec_batch={os.getenv('EXAMPAPER_REC_BATCH_SIZE')}, "
        f"prefetch={os.getenv('EXAMPAPER_PREFETCH_SIZE')}, "
        f"workers={os.getenv('EXAMPAPER_MAX_WORKERS')}"
    )
    print("=" * 50)


def run_web_server(
    host: str = "127.0.0.1",
    port: int = 8000,
    debug: bool = False,
    use_gpu: bool = True,
    workers: int = 4,
    warmup: bool = True,
):
    """启动Web服务器"""
    # Validate workers
    if workers < 1:
        print("[ERROR] workers must be >= 1")
        sys.exit(1)

    # Auto-detect hardware and GPU availability
    hardware = detect_hardware()
    gpu_detected = hardware.get("gpu_available", False)
    effective_use_gpu = use_gpu and gpu_detected
    if use_gpu and not gpu_detected:
        print("\n[WARN] GPU requested but not detected; falling back to CPU.")

    # Setup environment before importing app (pass hardware to avoid double detection)
    setup_environment(use_gpu=effective_use_gpu, workers=workers, warmup=warmup, hardware=hardware)

    print("\n" + "=" * 50)
    print("  ExamPaper AI Web Server")
    print("=" * 50)

    # Cleanup port
    print(f"\n[Cleanup] Checking port {port}...")
    if not cleanup_port(port):
        print("[WARN] Could not free port, server may fail to start")

    # Print config
    print_config_summary(effective_use_gpu, workers, warmup, gpu_detected, hardware)

    try:
        import uvicorn
        from backend.src.web.main import app

        print(f"\n[Starting] Launching server...")
        print(f"  URL: http://{host}:{port}")
        print(f"  Debug: {'ON' if debug else 'OFF'}")
        if warmup:
            print(f"  Model warmup: ~15-30s (background, non-blocking)")
        print(f"\nPress Ctrl+C to stop.\n")

        uvicorn.run(app, host=host, port=port, reload=debug)
    except ImportError as e:
        print(f"[ERROR] Cannot load Web module: {e}")
        print("Likely missing a dependency for the web server.")
        print("Try: pip install -r web_requirements.txt")
        print("If you want API rate limiting: pip install slowapi")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\n\n[INFO] Web server stopped")


def main():
    """主函数"""
    parser = argparse.ArgumentParser(
        description="PDF试卷自动切题与结构化工具 - 统一管理入口",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python manage.py                           # 启动Web服务器（默认，GPU优化已内置）
  python manage.py web                       # 启动Web服务器
  python manage.py web --port 9000          # 在9000端口启动Web服务器
  python manage.py web --no-gpu             # 禁用GPU加速
  python manage.py web --workers 8          # 设置并行工作线程数
  python manage.py web --no-warmup          # 禁用模型预热

访问 http://localhost:8000 使用完整功能
        """,
    )

    # 添加子命令
    subparsers = parser.add_subparsers(dest="command", help="可用命令")

    # Web命令
    parser_web = subparsers.add_parser("web", help="启动Web服务器")
    parser_web.add_argument("--host", default="127.0.0.1", help="服务器地址")
    parser_web.add_argument("--port", type=int, default=8000, help="服务器端口")
    parser_web.add_argument("--debug", action="store_true", help="开启调试模式")
    parser_web.add_argument("--no-gpu", action="store_true", help="禁用GPU加速")
    parser_web.add_argument("--workers", type=int, default=4, help="并行工作线程数 (默认: 4)")
    parser_web.add_argument("--no-warmup", action="store_true", help="禁用模型预热")

    args = parser.parse_args()

    # 如果没有指定命令，默认启动Web服务器
    if not args.command:
        run_web_server()
        return

    # 根据命令执行相应操作
    if args.command == "web":
        run_web_server(
            host=args.host,
            port=args.port,
            debug=args.debug,
            use_gpu=not args.no_gpu,
            workers=args.workers,
            warmup=not args.no_warmup,
        )
    else:
        parser.print_help()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n程序已退出")
        sys.exit(0)
    except Exception as e:
        print(f"\n发生错误: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
