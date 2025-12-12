#!/usr/bin/env python3
"""
manage.py - 项目统一管理入口

提供以下功能：
- Web服务器启动（推荐）
- 单文件快速处理（开发中）
- 批量处理（开发中）

使用方法：
    python manage.py                    # 启动Web服务器（默认）
    python manage.py web                # 启动Web服务器
    python manage.py web --port 9000    # 在指定端口启动Web服务器
    python manage.py process <file>     # 快速处理单个PDF（开发中）
    python manage.py batch <dir>        # 批量处理目录下的所有PDF（开发中）

注意：v2.0.1已统一使用Web界面，CLI模式已移除
"""

import sys
import argparse
from pathlib import Path


def run_web_server(host: str = "127.0.0.1", port: int = 8000, debug: bool = False):
    """启动Web服务器"""
    try:
        from web_interface.app import app

        print(f"\n🌐 启动Web服务器...")
        print(f"   地址: http://{host}:{port}")
        print(f"   调试模式: {'开启' if debug else '关闭'}")
        print(f"\n按 Ctrl+C 停止服务器\n")

        app.run(host=host, port=port, debug=debug)
    except ImportError as e:
        print(f"错误: 无法加载Web模块: {e}")
        print("请确保web_interface/app.py文件存在且可访问。")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\n\n👋 Web服务器已停止")


def process_single_file(pdf_path: str, config_path: str | None = None):
    """处理单个PDF文件"""
    pdf_file = Path(pdf_path)
    if not pdf_file.exists():
        print(f"错误: 文件不存在: {pdf_path}")
        sys.exit(1)

    print(f"\n📄 处理文件: {pdf_file.name}")

    # TODO: 实现单文件处理逻辑
    print("⚠️  单文件处理功能正在开发中...")
    print("   请使用Web界面进行处理：python manage.py web")


def process_batch(directory: str, config_path: str | None = None):
    """批量处理目录下的PDF文件"""
    dir_path = Path(directory)
    if not dir_path.exists() or not dir_path.is_dir():
        print(f"错误: 目录不存在: {directory}")
        sys.exit(1)

    pdf_files = list(dir_path.glob("*.pdf"))
    if not pdf_files:
        print(f"错误: 目录中没有找到PDF文件: {directory}")
        sys.exit(1)

    print(f"\n📦 批量处理目录: {dir_path}")
    print(f"   找到 {len(pdf_files)} 个PDF文件")

    # TODO: 实现批量处理逻辑
    print("⚠️  批量处理功能正在开发中...")
    print("   请使用Web界面进行处理：python manage.py web")


def main():
    """主函数"""
    parser = argparse.ArgumentParser(
        description="PDF试卷自动切题与结构化工具 - 统一管理入口",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python manage.py                           # 启动Web服务器（默认）
  python manage.py web                       # 启动Web服务器
  python manage.py web --port 9000          # 在9000端口启动Web服务器
  python manage.py web --debug              # 开启调试模式启动Web服务器
  python manage.py process input.pdf        # 处理单个PDF（开发中）
  python manage.py batch ./pdfs/            # 批量处理目录（开发中）

注意：v2.0.1已统一使用Web界面，访问 http://localhost:8000 使用完整功能
更多信息请访问: docs/README.md
        """,
    )

    # 添加子命令
    subparsers = parser.add_subparsers(dest="command", help="可用命令")

    # Web命令
    parser_web = subparsers.add_parser("web", help="启动Web服务器")
    parser_web.add_argument("--host", default="127.0.0.1", help="服务器地址")
    parser_web.add_argument("--port", type=int, default=8000, help="服务器端口")
    parser_web.add_argument("--debug", action="store_true", help="开启调试模式")

    # Process命令
    parser_process = subparsers.add_parser("process", help="处理单个PDF文件")
    parser_process.add_argument("file", help="PDF文件路径")
    parser_process.add_argument(
        "--config", help="配置文件路径（可选）", default=None
    )

    # Batch命令
    parser_batch = subparsers.add_parser("batch", help="批量处理目录下的PDF")
    parser_batch.add_argument("directory", help="包含PDF文件的目录路径")
    parser_batch.add_argument("--config", help="配置文件路径（可选）", default=None)

    args = parser.parse_args()

    # 如果没有指定命令，默认启动Web服务器
    if not args.command:
        run_web_server()
        return

    # 根据命令执行相应操作
    if args.command == "web":
        run_web_server(host=args.host, port=args.port, debug=args.debug)
    elif args.command == "process":
        process_single_file(args.file, args.config)
    elif args.command == "batch":
        process_batch(args.directory, args.config)
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
