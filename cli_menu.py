import subprocess
import sys
import os
from pathlib import Path
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt, Confirm
from rich.markdown import Markdown
from rich.table import Table
from rich import print as rprint

console = Console()


def clear_screen():
    os.system("cls" if os.name == "nt" else "clear")


def show_header():
    console.print(
        Panel.fit(
            "[bold cyan]?? 试卷自动切题与结构化工具 (Gemini CLI Wrapper)[/bold cyan]\n"
            "[dim]Automated Exam Question Extraction & Analysis[/dim]",
            border_style="cyan",
        )
    )


def get_target_directory():
    """获取要处理的目标目录。优先读取最近一次处理的目录。"""
    base_dir = Path("pdf_images")
    if not base_dir.exists():
        base_dir.mkdir()

    # 尝试读取上次的记录
    last_processed_file = base_dir / ".last_processed"
    default_subdir = None
    if last_processed_file.exists():
        try:
            name = last_processed_file.read_text(encoding="utf-8").strip()
            if (base_dir / name).is_dir():
                default_subdir = name
        except Exception:
            pass

    # 列出所有子目录
    subdirs = [d.name for d in base_dir.iterdir() if d.is_dir()]
    if not subdirs:
        # 如果没有子目录，说明可能还没运行过步骤0，或者用的是旧模式
        # 返回根目录
        return base_dir

    if default_subdir and default_subdir in subdirs:
        # 自动确认模式（稍微简化操作）
        console.print(
            f"[dim]默认处理最近的试卷: [bold cyan]{default_subdir}[/bold cyan][/dim]"
        )
        # 如果你想每次都手动选，可以把这里改为询问
        return base_dir / default_subdir

    # 如果没有默认值，或者有多个且没有记录，让用户选（这里简化为默认选第一个，或者你可以加个选择逻辑）
    # 为保持 CLI 简洁，这里默认选最新的一个文件夹（按修改时间）
    latest_subdir = sorted(
        subdirs, key=lambda x: (base_dir / x).stat().st_mtime, reverse=True
    )[0]
    console.print(
        f"[dim]自动选择最新的试卷目录: [bold cyan]{latest_subdir}[/bold cyan][/dim]"
    )
    return base_dir / latest_subdir


def show_help():
    help_text = """
# ?? 项目使用说明

这个工具用于自动化处理 PDF 试卷截图。主要流程如下：

1. **基础切题 (`extract_questions_ppstruct.py`)**:
   - 核心步骤。将每一页 (`page_*.png`) 的题目自动切割出来。
   - 生成结果在 `questions_page_X` 文件夹中。

2. **资料分析聚合 (`make_data_analysis_big.py`)**:
   - 针对“资料分析”这种一个材料对应多个小题的情况。
   - 它会将跨页的材料和小题合并成“大题截图” (`big_*.png`)。
   - 必须先运行第1步。

3. **AI 分析 (ChatOCR / VL)**:
   - 可选步骤。使用大模型对题目进行语义理解或结构化提取。
   - 需要配置 `chatocr_config.json`。
    """
    console.print(Markdown(help_text))
    Prompt.ask("\n按回车键返回主菜单")


def run_extract_questions():
    console.print(
        Panel(
            "[bold green]??  切分试题 (Extract Questions)[/bold green]",
            border_style="green",
        )
    )

    target_dir = get_target_directory()
    console.print(f"[blue]当前工作目录: {target_dir}[/blue]")

    console.print(
        "[dim][bold]all[/]: 处理所有页面 | [bold]specific[/]: 指定页码 | [bold]back[/]: 返回[/dim]"
    )
    choice = Prompt.ask(
        "选择处理范围",
        choices=["all", "specific", "back"],
        default="all",
        show_choices=False,
    )

    # 构造命令，加入 --dir 参数
    cmd = [sys.executable, "extract_questions_ppstruct.py", "--dir", str(target_dir)]

    if choice == "back":
        return
    elif choice == "specific":
        pages = Prompt.ask("请输入页码 (用空格分隔, 例如: 6 7 13)")
        if pages.strip():
            cmd.extend(pages.split())
        else:
            console.print("[yellow]未输入页码，操作取消[/yellow]")
            return

    console.print(f"[dim]执行命令: {' '.join(cmd)}[/dim]")
    try:
        subprocess.run(cmd, check=True)
        console.print("[bold green]? 执行完成！[/bold green]")
    except subprocess.CalledProcessError:
        console.print("[bold red]? 执行出错，请检查错误日志。[/bold red]")
    except KeyboardInterrupt:
        console.print("\n[yellow]操作已取消[/yellow]")

    Prompt.ask("按回车键继续")


def run_basic_pdf_to_questions_flow():
    """
    一键流程：
    1）运行 pdf_to_images.py，把当前目录下选中的 PDF 转成 page_*.png；
    2）自动选择刚才那套试卷目录，运行 extract_questions_ppstruct.py 做切题。
    """
    console.print(
        Panel(
            "[bold green]?? 一键从 PDF 到题目切图[/bold green]",
            border_style="green",
        )
    )

    # 第一步：PDF -> page_*.png
    cmd_pdf = [sys.executable, "pdf_to_images.py"]
    console.print(f"[dim]执行命令: {' '.join(cmd_pdf)}[/dim]")
    try:
        subprocess.run(cmd_pdf, check=True)
    except subprocess.CalledProcessError:
        console.print("[bold red]? PDF 转图片步骤出错，请检查错误日志。[/bold red]")
        Prompt.ask("按回车键返回主菜单")
        return
    except KeyboardInterrupt:
        console.print("\n[yellow]操作已取消[/yellow]")
        Prompt.ask("按回车键返回主菜单")
        return

    # 第二步：根据 .last_processed 自动选择试卷目录并切题
    target_dir = get_target_directory()
    console.print(f"[blue]切题目标目录: {target_dir}[/blue]")

    cmd_cut = [sys.executable, "extract_questions_ppstruct.py", "--dir", str(target_dir)]
    console.print(f"[dim]执行命令: {' '.join(cmd_cut)}[/dim]")
    try:
        subprocess.run(cmd_cut, check=True)
        console.print("[bold green]? 一键切题完成！[/bold green]")
    except subprocess.CalledProcessError:
        console.print("[bold red]? 切分试题步骤出错，请检查错误日志。[/bold red]")
        Prompt.ask("按回车键继续")
        return
    except KeyboardInterrupt:
        console.print("\n[yellow]操作已取消[/yellow]")
        Prompt.ask("按回车键继续")
        return

    # 第三步：生成资料分析大题结构（可选，失败不影响后续）
    cmd_big = [sys.executable, "make_data_analysis_big.py", "--dir", str(target_dir)]
    console.print(f"[dim]执行命令: {' '.join(cmd_big)}[/dim]")
    try:
        subprocess.run(cmd_big, check=True)
        console.print("[green]资料分析大题结构生成完成。[/green]")
    except Exception:
        console.print("[yellow]资料分析大题步骤失败或跳过，继续后续流程。[/yellow]")

    # 第四步：拼接小题 / 资料分析大题长图（可选，失败不影响后续）
    cmd_long = [
        sys.executable,
        "compose_question_long_image.py",
        "--dir",
        str(target_dir),
    ]
    console.print(f"[dim]执行命令: {' '.join(cmd_long)}[/dim]")
    try:
        subprocess.run(cmd_long, check=True)
        console.print("[green]长图拼接完成（小题和资料分析大题，如有）。[/green]")
    except Exception:
        console.print("[yellow]长图拼接步骤失败或跳过，继续后续流程。[/yellow]")

    # 第五步：在该试卷目录下汇总所有题目的图片到一个统一文件夹
    try:
        collect_all_question_images(target_dir)
        console.print("[bold green]? 已在试卷目录下汇总所有题目图片。[/bold green]")
    except Exception as e:
        console.print(f"[bold red]? 汇总题目图片时出错: {e}[/bold red]")

    Prompt.ask("按回车键继续")


def collect_all_question_images(target_dir: Path) -> None:
    """
    在指定试卷目录下创建一个统一的汇总文件夹 all_questions：
    - 对每个 questions_page_X/meta.json 中的每道小题：
      - 如果存在 q['long_image'] 且文件存在，则优先使用长图；
      - 否则使用 q['image'] 对应的原始单题图；
    - 如果存在资料分析大题（big_questions），且有 bq['combined_image']，
      则将其也拷贝到同一目录下。

    这样你只要打开 all_questions 文件夹，就能看到这一套卷子的所有题目图片；
    若之前已经做过长图拼接，会自动优先选用拼接好的版本。
    """
    import json
    import shutil

    img_dir = target_dir
    all_dir = img_dir / "all_questions"
    # 每次汇总前清空旧内容，避免遗留错误版本
    if all_dir.exists():
        for child in all_dir.iterdir():
            try:
                if child.is_file():
                    child.unlink()
            except Exception:
                pass
    else:
        all_dir.mkdir(parents=True, exist_ok=True)

    meta_paths = sorted(
        img_dir.glob("questions_page_*/meta.json"),
        key=lambda p: int(p.parent.name.replace("questions_page_", "") or "0"),
    )
    if not meta_paths:
        console.print(
            f"[yellow]未在 {img_dir} 下找到任何 questions_page_*/meta.json，跳过汇总。[/yellow]"
        )
        return

    # 先读入所有 meta，并收集“需要跳过的小题题号”（即已归属于资料分析大题的小题）
    metas = []
    qnos_to_skip = set()
    for meta_path in meta_paths:
        with meta_path.open("r", encoding="utf-8") as f:
            meta = json.load(f)
        metas.append(meta)
        for bq in meta.get("big_questions", []):
            # 默认所有 big_questions 对应的小题都视为资料分析等大题的小问
            for qno in bq.get("qnos", []):
                if isinstance(qno, int):
                    qnos_to_skip.add(qno)

    used_names = set()

    def copy_with_unique_name(src: Path, base_name: str) -> None:
        name = base_name
        stem = Path(base_name).stem
        suffix = Path(base_name).suffix or ".png"
        idx = 2
        while name in used_names:
            name = f"{stem}_{idx}{suffix}"
            idx += 1
        used_names.add(name)
        dst = all_dir / name
        shutil.copy2(src, dst)

    for meta in metas:
        # 1) 小题
        for q in meta.get("questions", []):
            qno = q.get("qno")
            # 如果该小题题号属于某个 big_question（如资料分析 71–90 小题），则不再单独汇总
            if isinstance(qno, int) and qno in qnos_to_skip:
                continue

            img_path_str = None
            # 优先长图
            if q.get("long_image"):
                img_path_str = q["long_image"]
            else:
                img_path_str = q.get("image")
            if not img_path_str:
                continue
            src = Path(img_path_str)
            if not src.is_file():
                src = (img_dir.parent / img_path_str).resolve()
            if not src.is_file():
                continue

            if qno is None:
                base_name = src.name
            else:
                base_name = f"q{qno}.png"
            copy_with_unique_name(src, base_name)

        # 2) 资料分析大题（如有）
        for bq in meta.get("big_questions", []):
            combined = bq.get("combined_image")
            if not combined:
                continue
            src = Path(combined)
            if not src.is_file():
                src = (img_dir.parent / combined).resolve()
            if not src.is_file():
                continue

            bid = str(bq.get("id") or "big_question")
            base_name = f"{bid}.png"
            copy_with_unique_name(src, base_name)


def run_script(script_name, description):
    console.print(Panel(f"[bold blue]{description}[/bold blue]", border_style="blue"))

    if not Path(script_name).exists():
        console.print(f"[bold red]? 找不到脚本文件: {script_name}[/bold red]")
        Prompt.ask("按回车键返回")
        return

    cmd = [sys.executable, script_name]

    # 特殊处理：如果是切题或资料分析 / 长图脚本，需要传入目录参数
    if script_name in [
        "make_data_analysis_big.py",
        "compose_question_long_image.py",
    ]:
        target_dir = get_target_directory()
        console.print(f"[blue]当前工作目录: {target_dir}[/blue]")
        cmd.extend(["--dir", str(target_dir)])

    if script_name == "run_chatocr_on_big_questions.py":
        if not Path("chatocr_config.json").exists():
            console.print("[yellow]??  警告: 未找到 chatocr_config.json 配置文件。[/yellow]")
            if not Confirm.ask("是否继续运行？(可能报错)"):
                return

    console.print(f"[dim]执行命令: {' '.join(cmd)}[/dim]")

    try:
        subprocess.run(cmd, check=True)
        console.print("[bold green]? 执行完成！[/bold green]")
    except subprocess.CalledProcessError:
        console.print("[bold red]? 执行出错。[/bold red]")
    except KeyboardInterrupt:
        console.print("\n[yellow]操作已取消[/yellow]")

    Prompt.ask("按回车键继续")


def main_menu():
    while True:
        clear_screen()
        show_header()

        table = Table(show_header=False, box=None)
        table.add_column("Key", style="cyan bold", width=4)
        table.add_column("Description")

        table.add_row(
            "0",
            "?? PDF 转图片 (PDF to Images) [bold yellow]Start Here![/bold yellow]",
        )
        table.add_row("1", "??  切分试题 (Extract Questions)")
        table.add_row("2", "?? 处理资料分析大题 (Process Data Analysis)")
        table.add_row("3", "?? 运行 ChatOCR (LLM Analysis)")
        table.add_row("4", "???  运行 VL Model (Visual Analysis)")
        table.add_row(
            "5", "?? 拼接跨页小题 / 大题长图 (Compose Long Images for Questions & Big Qs)"
        )
        table.add_row("6", "?? 一键从 PDF 到题目切图 (Basic One-shot Flow)")
        table.add_row("7", "? 帮助 / 说明 (Help)")
        table.add_row("8", "?? 退出 (Exit)")

        console.print(table)
        console.print("\n[dim]请使用数字键选择操作[/dim]")

        choice = Prompt.ask(
            "输入选项",
            choices=["0", "1", "2", "3", "4", "5", "6", "7", "8"],
            show_choices=False,
        )

        if choice == "0":
            run_script("pdf_to_images.py", "?? PDF 转图片 (PDF to Images)")
        elif choice == "1":
            run_extract_questions()
        elif choice == "2":
            run_script("make_data_analysis_big.py", "处理资料分析大题")
        elif choice == "3":
            run_script("run_chatocr_on_big_questions.py", "运行 ChatOCR (LLM Analysis)")
        elif choice == "4":
            run_script("run_vl_on_big_questions.py", "运行 VL Model (Visual Analysis)")
        elif choice == "5":
            run_script(
                "compose_question_long_image.py",
                "拼接跨页小题 / 大题长图 (Compose Long Images for Questions & Big Qs)",
            )
        elif choice == "6":
            run_basic_pdf_to_questions_flow()
        elif choice == "7":
            show_help()
        elif choice == "8":
            console.print("[bold cyan]?? 再见！[/bold cyan]")
            break


if __name__ == "__main__":
    main_menu()
