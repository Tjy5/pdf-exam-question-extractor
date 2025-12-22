#!/usr/bin/env python3
"""
home.py - 启动前后端并自动打开主页

一键启动开发环境并在浏览器中打开主页。

使用方法：
    python home.py              # 启动前后端并打开浏览器
    python home.py --no-browser # 启动但不自动打开浏览器
    python home.py --port 9000  # 指定后端端口
"""

import os
import sys
import signal
import subprocess
import argparse
import time
import socket
import webbrowser
import psutil
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent


def load_env_file(env_path: Path = None):
    """加载 .env 文件到环境变量"""
    if env_path is None:
        env_path = PROJECT_ROOT / "backend" / ".env"

    if not env_path.exists():
        print(f"[Warning] .env 文件不存在: {env_path}")
        return

    print(f"[Config] 加载配置文件: {env_path}")
    with open(env_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip()
                if value.startswith('"') and value.endswith('"'):
                    value = value[1:-1]
                elif value.startswith("'") and value.endswith("'"):
                    value = value[1:-1]
                if "#" in value:
                    value = value.split("#")[0].strip()
                os.environ[key] = value

    ai_provider = os.environ.get("AI_PROVIDER", "mock")
    ai_model = os.environ.get("AI_MODEL", "N/A")
    has_key = bool(os.environ.get("AI_API_KEY"))
    print(f"[Config] AI_PROVIDER={ai_provider}, AI_MODEL={ai_model}, has_key={has_key}")


def check_port(port: int) -> bool:
    """检查端口是否被占用"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


def kill_process_on_port(port: int):
    """杀死占用指定端口的进程"""
    print(f"[Cleanup] 检查端口 {port}...")
    killed = False

    for proc in psutil.process_iter(['pid', 'name', 'connections']):
        try:
            connections = proc.connections()
            for conn in connections:
                if conn.laddr.port == port and conn.status == 'LISTEN':
                    print(f"[Cleanup] 发现进程占用端口 {port}: PID={proc.pid}, Name={proc.name()}")
                    proc.terminate()
                    try:
                        proc.wait(timeout=3)
                        print(f"[Cleanup] 进程 {proc.pid} 已终止")
                    except psutil.TimeoutExpired:
                        proc.kill()
                        print(f"[Cleanup] 进程 {proc.pid} 已强制终止")
                    killed = True
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass

    if not killed:
        print(f"[Cleanup] 端口 {port} 空闲")
    else:
        time.sleep(1)


def run_backend(port: int = 8000):
    """启动后端服务"""
    env = os.environ.copy()
    env["APP_MODE"] = "dev"

    print(f"[Backend] 环境变量 AI_PROVIDER={env.get('AI_PROVIDER', 'mock')}")
    print(f"[Backend] 环境变量 AI_MODEL={env.get('AI_MODEL', 'N/A')}")

    return subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "backend.src.web.main:app",
         "--host", "127.0.0.1", "--port", str(port), "--reload"],
        cwd=PROJECT_ROOT,
        env=env,
    )


def run_frontend():
    """启动前端开发服务器"""
    frontend_dir = PROJECT_ROOT / "frontend"

    npm_cmd = "npm.cmd" if sys.platform == "win32" else "npm"

    env = os.environ.copy()
    env["APP_MODE"] = "dev"

    return subprocess.Popen(
        [npm_cmd, "run", "dev"],
        cwd=frontend_dir,
        shell=sys.platform == "win32",
        env=env,
    )


def wait_for_server(url: str, timeout: int = 30) -> bool:
    """等待服务器启动"""
    import urllib.request
    import urllib.error

    start_time = time.time()
    while time.time() - start_time < timeout:
        try:
            urllib.request.urlopen(url, timeout=1)
            return True
        except (urllib.error.URLError, ConnectionError, TimeoutError):
            time.sleep(0.5)
    return False


def open_browser(url: str, delay: float = 2):
    """延迟后打开浏览器"""
    time.sleep(delay)
    print(f"\n[Browser] 正在打开浏览器: {url}")
    try:
        webbrowser.open(url)
    except Exception as e:
        print(f"[Browser] 无法自动打开浏览器: {e}")
        print(f"[Browser] 请手动访问: {url}")


def main():
    parser = argparse.ArgumentParser(description="启动前后端并打开主页")
    parser.add_argument("--port", type=int, default=8000, help="后端端口 (默认: 8000)")
    parser.add_argument("--no-browser", action="store_true", help="不自动打开浏览器")
    parser.add_argument("--no-cleanup", action="store_true", help="不自动清理占用端口的进程")
    args = parser.parse_args()

    processes = []

    print("=" * 60)
    print("  智能试卷处理与答疑平台 - 主页启动")
    print("=" * 60)

    try:
        print("\n[Step 1] 加载配置文件...")
        load_env_file()

        if not args.no_cleanup:
            print(f"\n[Step 2] 端口保护机制...")
            backend_port = args.port
            frontend_port = 5173

            for port in [backend_port, frontend_port]:
                if check_port(port):
                    print(f"[Warning] 端口 {port} 已被占用")
                    kill_process_on_port(port)
                    if check_port(port):
                        print(f"[Error] 无法释放端口 {port}，请手动检查")
                        sys.exit(1)
                else:
                    print(f"[OK] 端口 {port} 可用")

        print(f"\n[Step 3] 启动服务...")
        print(f"[Backend] 启动后端服务 (port {args.port})...")
        backend_proc = run_backend(args.port)
        processes.append(("Backend", backend_proc))
        time.sleep(2)

        print("\n[Frontend] 启动前端开发服务器...")
        frontend_proc = run_frontend()
        processes.append(("Frontend", frontend_proc))

        print("\n" + "=" * 60)
        print("  服务已启动")
        print("=" * 60)
        print(f"  后端 API:  http://127.0.0.1:{args.port}")
        print(f"  API 文档:  http://127.0.0.1:{args.port}/docs")
        print(f"  前端页面:  http://localhost:5173")
        print(f"  主页入口:  http://localhost:5173/")
        print("=" * 60)

        if not args.no_browser:
            print("\n[Step 4] 等待服务就绪...")
            frontend_url = "http://localhost:5173"

            print("[Waiting] 等待前端服务器启动 (最多30秒)...")
            if wait_for_server(frontend_url, timeout=30):
                print("[OK] 前端服务器已就绪")
                open_browser(frontend_url, delay=1)
            else:
                print("[Warning] 前端服务器启动超时")
                print(f"[Info] 请稍后手动访问: {frontend_url}")

        print("\n  按 Ctrl+C 停止所有服务\n")

        while True:
            for name, proc in processes:
                ret = proc.poll()
                if ret is not None:
                    print(f"\n[{name}] 进程已退出 (code={ret})")
                    raise KeyboardInterrupt
            time.sleep(1)

    except KeyboardInterrupt:
        print("\n\n[Shutdown] 正在停止所有服务...")
        for name, proc in processes:
            if proc.poll() is None:
                print(f"  停止 {name}...")
                if sys.platform == "win32":
                    proc.terminate()
                else:
                    proc.send_signal(signal.SIGTERM)
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
        print("[Done] 所有服务已停止")


if __name__ == "__main__":
    main()
