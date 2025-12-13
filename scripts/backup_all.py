"""
完整备份工具 - 将数据库和图片一起打包

Usage:
    python scripts/backup_all.py [--output backup.zip]
"""

import asyncio
import sys
import zipfile
from pathlib import Path
from datetime import datetime

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def backup_all(output_path: Path = None):
    """
    Create a complete backup including database and images.

    Args:
        output_path: Output zip file path (default: backup_YYYYMMDD_HHMMSS.zip)
    """
    if output_path is None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = PROJECT_ROOT / f"backup_{timestamp}.zip"

    print("=" * 60)
    print("完整备份工具")
    print("=" * 60)
    print(f"输出文件: {output_path}")

    with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
        # 备份数据库
        db_path = PROJECT_ROOT / "data" / "tasks.db"
        if db_path.exists():
            print(f"\n[1/2] 备份数据库: {db_path.stat().st_size / 1024:.2f} KB")
            zipf.write(db_path, "data/tasks.db")

        # 备份所有图片
        print(f"\n[2/2] 备份图片目录...")
        pdf_images_dir = PROJECT_ROOT / "pdf_images"
        if pdf_images_dir.exists():
            count = 0
            total_size = 0
            for file_path in pdf_images_dir.rglob("*"):
                if file_path.is_file():
                    arcname = file_path.relative_to(PROJECT_ROOT)
                    zipf.write(file_path, arcname)
                    count += 1
                    total_size += file_path.stat().st_size
                    if count % 100 == 0:
                        print(f"  已备份 {count} 个文件...")

            print(f"  ✓ 共备份 {count} 个文件，{total_size / (1024*1024):.2f} MB")

    final_size = output_path.stat().st_size / (1024*1024)
    print("\n" + "=" * 60)
    print(f"✅ 备份完成！")
    print(f"备份文件: {output_path}")
    print(f"压缩后大小: {final_size:.2f} MB")
    print("=" * 60)

    return output_path


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="备份数据库和图片")
    parser.add_argument("--output", type=Path, help="输出zip文件路径")
    args = parser.parse_args()

    backup_all(args.output)
