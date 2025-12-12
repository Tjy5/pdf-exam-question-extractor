import argparse
import json
from pathlib import Path
from typing import Any, Dict, List

from paddleocr import PPChatOCRv4Doc

from common import iter_meta_paths, resolve_image_path, auto_latest_exam_dir


ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "chatocr_config.json"


def load_chat_bot_config() -> Dict[str, Any]:
    """
    从 chatocr_config.json 读取大模型配置。

    示例（仅供参考，请根据自己的服务修改）::

        {
          "chat_bot_config": {
            "module_name": "chat_bot",
            "model_name": "ernie-3.5-8k",
            "base_url": "https://qianfan.baidubce.com/v2",
            "api_type": "openai",
            "api_key": "your_api_key_here"
          }
        }
    """
    if not CONFIG_PATH.is_file():
        raise SystemExit(
            f"未找到 {CONFIG_PATH}，请先创建并填写 chat_bot_config（参考文件头部注释）。"
        )
    data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    cfg = data.get("chat_bot_config")
    if not isinstance(cfg, dict):
        raise SystemExit("chatocr_config.json 中缺少 chat_bot_config 字段或类型不正确。")
    return cfg


def run_chatocr_on_meta(
    meta_path: Path,
    pipeline: PPChatOCRv4Doc,
    chat_bot_config: Dict[str, Any],
    img_dir: Path,
) -> None:
    """
    对某一页的 big_questions 段落运行 PP-ChatOCRv4，将摘要写回 meta.json。

    输出字段示例：
        big_questions[*].segments[*].chatocr_chat_res
    """
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    big_questions: List[Dict[str, Any]] = meta.get("big_questions") or []
    if not big_questions:
        return

    changed = False
    for bq in big_questions:
        segments = bq.get("segments") or []
        for seg in segments:
            img_path = seg.get("image")
            # 已经跑过的不重复调用
            if not img_path or "chatocr_chat_res" in seg:
                continue

            # 解析相对路径为可用的绝对路径
            img_abs = resolve_image_path(str(img_path), img_dir.parent)
            if not img_abs.is_file():
                print(f"[ChatOCR][WARN] 找不到图片: {img_path}（解析到 {img_abs}），已跳过")
                continue

            print(f"[ChatOCR] {meta_path.name} - {bq.get('id')} - {img_abs}")
            visual_info = pipeline.visual_predict(input=str(img_abs))

            # 这里给一个默认的“摘要型”任务描述，你可以在需要时调整 prompt
            chat_res = pipeline.chat(
                key_list=["材料主题", "核心结论"],
                visual_info=visual_info,
                chat_bot_config=chat_bot_config,
                text_task_description="请阅读整张图片对应的资料分析大题，提取：1）材料主题；2）最关键的结论或趋势，用简短中文回答。",
                text_output_format="JSON",
            )

            seg["chatocr_chat_res"] = chat_res
            changed = True

    if changed:
        meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run ChatOCR on big questions (资料分析等) and write back to meta.json"
    )
    parser.add_argument(
        "--dir",
        type=str,
        default=None,
        help="Directory containing questions_page_*/meta.json (可指向具体试卷子目录); if omitted auto-select latest under pdf_images",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    img_dir = Path(args.dir).resolve() if args.dir else auto_latest_exam_dir().resolve()
    if not img_dir.is_dir():
        raise SystemExit(f"目录不存在: {img_dir}")

    chat_bot_config = load_chat_bot_config()
    pipeline = PPChatOCRv4Doc()

    for meta_path in iter_meta_paths(img_dir):
        run_chatocr_on_meta(meta_path, pipeline, chat_bot_config, img_dir)


if __name__ == "__main__":
    main()
