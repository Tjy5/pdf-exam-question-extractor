import fitz  # PyMuPDF
import sys
import re
from pathlib import Path
from rich.console import Console
from rich.prompt import Prompt
from rich.progress import track

console = Console()

def clean_filename(name):
    """清理文件名，移除空格和特殊字符，避免路径问题"""
    # 移除扩展名
    stem = Path(name).stem
    # 替换空格和非单词字符为下划线
    clean = re.sub(r'[^\w\u4e00-\u9fa5]+', '_', stem)
    return clean.strip('_')

def get_pdf_files():
    return list(Path(".").glob("*.pdf"))

def convert_pdf_to_images():
    pdfs = get_pdf_files()
    
    if not pdfs:
        console.print("[bold red]❌ 当前目录下没有找到 PDF 文件！[/bold red]")
        return

    # 选择 PDF
    if len(pdfs) == 1:
        target_pdf = pdfs[0]
        console.print(f"[bold cyan]找到文件: {target_pdf.name}[/bold cyan]")
    else:
        console.print("[yellow]当前目录下有多个 PDF，请选择:[/yellow]")
        for idx, p in enumerate(pdfs):
            console.print(f"{idx + 1}. {p.name}")
        
        choice = Prompt.ask("请输入序号", choices=[str(i+1) for i in range(len(pdfs))])
        target_pdf = pdfs[int(choice) - 1]

    # 创建专属子目录
    folder_name = clean_filename(target_pdf.name)
    base_dir = Path("pdf_images")
    output_dir = base_dir / folder_name
    output_dir.mkdir(parents=True, exist_ok=True)
    
    console.print(f"[dim]正在读取: {target_pdf.name}...[/dim]")
    doc = fitz.open(target_pdf)
    total_pages = len(doc)
    
    console.print(f"[green]PDF 共 {total_pages} 页，准备转换...[/green]")
    console.print(f"[blue]目标文件夹: {output_dir}[/blue]")

    # 转换循环
    for i in track(range(total_pages), description="Converting pages..."):
        page = doc.load_page(i)
        # 设置缩放系数，3.0 约为 200-300 DPI
        mat = fitz.Matrix(3.0, 3.0)
        pix = page.get_pixmap(matrix=mat)
        
        # 保存为 page_1.png, page_2.png ...
        output_filename = output_dir / f"page_{i + 1}.png"
        pix.save(output_filename)

    console.print(f"\n[bold green]✅ 转换完成！[/bold green]")
    console.print(f"图片已保存在: [underline]{output_dir}[/underline]")
    
    # 保存最近一次操作的目录到临时文件，供 cli_menu 读取（可选优化）
    try:
        (base_dir / ".last_processed").write_text(folder_name, encoding="utf-8")
    except Exception:
        pass

if __name__ == "__main__":
    try:
        convert_pdf_to_images()
    except KeyboardInterrupt:
        console.print("\n[yellow]操作已取消[/yellow]")
    except Exception as e:
        console.print(f"\n[bold red]❌ 发生错误: {e}[/bold red]")