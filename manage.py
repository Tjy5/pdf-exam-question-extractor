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


# =============================================================================
# Environment Configuration (from start_web_production.bat)
# =============================================================================

DEFAULT_ENV_CONFIG = {
    # GPU Acceleration
    "EXAMPAPER_USE_GPU": "1",
    # GPU Memory Limit (80% to prevent OOM on 6GB cards)
    "FLAGS_fraction_of_gpu_memory_to_use": "0.8",
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
    # Async warmup (server starts immediately, model loads in background)
    "EXAMPAPER_PPSTRUCTURE_WARMUP_ASYNC": "1",
    # Fallback to subprocess if in-proc fails
    "EXAMPAPER_STEP1_FALLBACK_SUBPROCESS": "1",
    "EXAMPAPER_STEP2_FALLBACK_SUBPROCESS": "1",
    # Table recognition (keep enabled for data analysis)
    "EXAMPAPER_LIGHT_TABLE": "0",
    # Parallel extraction
    "EXAMPAPER_PARALLEL_EXTRACTION": "1",
    "EXAMPAPER_MAX_WORKERS": "4",
}


def detect_gpu_available() -> bool:
    """Check if NVIDIA GPU is available via nvidia-smi"""
    try:
        result = subprocess.run(
            ["nvidia-smi"], capture_output=True, timeout=5
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def setup_environment(use_gpu: bool = True, workers: int = 4, warmup: bool = True):
    """Setup environment variables for optimal performance"""
    for key, value in DEFAULT_ENV_CONFIG.items():
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
            capture_output=True, text=True, timeout=10
        )
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
    except (subprocess.TimeoutExpired, ValueError):
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


def print_config_summary(use_gpu: bool, workers: int, warmup: bool, gpu_detected: bool = True):
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
    print(f"  Parallel Workers: {workers}")
    print(f"  Model Warmup: {'ASYNC' if warmup else 'DISABLED'}")
    print(f"  In-process Execution: ENABLED")
    print(f"  Subprocess Fallback: ENABLED")
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

    # Auto-detect GPU and fallback to CPU if not available
    gpu_detected = detect_gpu_available()
    effective_use_gpu = use_gpu and gpu_detected
    if use_gpu and not gpu_detected:
        print("\n[WARN] GPU requested but not detected; falling back to CPU.")

    # Setup environment before importing app
    setup_environment(use_gpu=effective_use_gpu, workers=workers, warmup=warmup)

    print("\n" + "=" * 50)
    print("  ExamPaper AI Web Server")
    print("=" * 50)

    # Cleanup port
    print(f"\n[Cleanup] Checking port {port}...")
    if not cleanup_port(port):
        print("[WARN] Could not free port, server may fail to start")

    # Print config
    print_config_summary(effective_use_gpu, workers, warmup, gpu_detected)

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
        print("Please ensure backend/src/web/main.py exists.")
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
        print("\n\n👋 程序已退出")
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ 发生错误: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
