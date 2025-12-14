"""
ocr_models.py - OCR模型管理

提供PaddleOCR和PP-StructureV3的单例管理
"""

import inspect
import os
import threading
from pathlib import Path
from typing import Any, Optional


# 全局缓存
_pipeline_cache: Optional[Any] = None
_pipeline_lock = threading.Lock()
_pipeline_init_error: Optional[BaseException] = None


def get_offline_model_path(model_name: str) -> Path:
    """
    在无网络环境下返回 paddlex 官方模型的本地缓存路径。

    Args:
        model_name: 模型名称

    Returns:
        模型本地缓存路径

    Raises:
        FileNotFoundError: 离线模式下未找到模型目录
    """
    base = Path.home() / ".paddlex" / "official_models"
    local_dir = base / model_name
    if local_dir.is_dir():
        return local_dir
    raise FileNotFoundError(f"离线模式下未找到模型目录: {local_dir}")


def reset_ppstructure_cache() -> None:
    """Clear cached PP-StructureV3 instance and previous init error (if any)."""
    global _pipeline_cache, _pipeline_init_error
    with _pipeline_lock:
        _pipeline_cache = None
        _pipeline_init_error = None


def _parse_batch_env(env_name: str, default: int) -> int:
    """解析批量大小环境变量，无效值时返回默认值。"""
    raw = os.getenv(env_name, "").strip()
    if not raw:
        return default
    try:
        val = int(raw)
        return val if val > 0 else default
    except ValueError:
        print(f"[WARNING] Invalid {env_name}={raw!r}; using {default}")
        return default


def _create_ppstructure() -> Any:
    """
    Create a new PP-StructureV3 pipeline instance.

    NOTE: This does not use any global cache; callers should decide whether to
    cache or pool instances.
    """
    from paddleocr import PPStructureV3

    # 在无网络环境下强制使用本地缓存模型，避免 paddlex 强制联网下载
    try:
        from paddlex.inference.utils.official_models import official_models

        # 如果 hoster 列表为空（表示当前版本要求联网），则改为离线路径解析
        if getattr(official_models, "_hosters", []) == []:
            cls = official_models.__class__
            cls._get_model_local_path = (  # type: ignore[attr-defined,assignment]
                lambda self, name: get_offline_model_path(name)
            )
    except Exception:
        # 离线兜底失败时，按原逻辑继续（可能会再尝试联网）
        pass

    # GPU 加速配置
    # EXAMPAPER_USE_GPU=1 启用 GPU（默认启用）
    # EXAMPAPER_USE_GPU=0 强制使用 CPU
    # EXAMPAPER_GPU_ID=N 指定 GPU 编号（默认0）
    use_gpu_env = os.getenv("EXAMPAPER_USE_GPU", "1")
    use_gpu = use_gpu_env == "1"

    # 如果启用 GPU，先检测是否可用
    gpu_available = False
    gpu_count = 0
    if use_gpu:
        try:
            import paddle

            if paddle.device.is_compiled_with_cuda():
                gpu_count = paddle.device.cuda.device_count()
                gpu_available = gpu_count > 0

            if gpu_available:
                # 设置 GPU 显存分配策略（避免显存不足）
                # fraction=0.8 表示最多使用 80% 显存
                os.environ.setdefault("FLAGS_fraction_of_gpu_memory_to_use", "0.8")
        except Exception:
            gpu_available = False

    # 如果请求 GPU 但不可用，回退到 CPU 并警告
    if use_gpu and not gpu_available:
        print("[WARNING] GPU requested but not available, falling back to CPU")
        use_gpu = False

    # PPStructureV3 默认会加载表格/公式/图表等多套子模型，
    # 在 Web 场景里非常吃内存。切题/资料分析主要依赖版面与文字块，
    # 因此关闭不必要的分支以显著降低占用。
    light_table = os.getenv("EXAMPAPER_LIGHT_TABLE", "0") == "1"

    # PaddleOCR 3.x 使用 device 参数代替 use_gpu
    if use_gpu:
        # 验证 GPU ID 配置
        gpu_id_raw = (os.getenv("EXAMPAPER_GPU_ID", "0") or "0").strip()
        try:
            gpu_id = int(gpu_id_raw)
        except ValueError:
            print(f"[WARNING] Invalid EXAMPAPER_GPU_ID={gpu_id_raw!r}; using 0")
            gpu_id = 0

        # 验证 GPU ID 范围
        if gpu_id < 0 or gpu_id >= gpu_count:
            print(
                f"[WARNING] EXAMPAPER_GPU_ID={gpu_id} out of range "
                f"(0..{gpu_count - 1}); using 0"
            )
            gpu_id = 0

        device = f"gpu:{gpu_id}"
    else:
        device = "cpu"

    # 批量推理参数（提升GPU利用率）
    det_batch_size = _parse_batch_env("EXAMPAPER_DET_BATCH_SIZE", default=2)
    rec_batch_size = _parse_batch_env("EXAMPAPER_REC_BATCH_SIZE", default=16)

    pp_kwargs: dict[str, Any] = {
        "device": device,
        "use_doc_orientation_classify": False,
        "use_doc_unwarping": False,
        "use_formula_recognition": False,
        "use_chart_recognition": False,
        "use_seal_recognition": False,
        "use_table_recognition": not light_table,
    }

    # 兼容旧版 PPStructureV3：仅在构造函数支持时传入批大小
    try:
        sig = inspect.signature(PPStructureV3)
        if "det_batch_size" in sig.parameters:
            pp_kwargs["det_batch_size"] = det_batch_size
        if "rec_batch_size" in sig.parameters:
            pp_kwargs["rec_batch_size"] = rec_batch_size
    except Exception:
        pass

    try:
        return PPStructureV3(**pp_kwargs)
    except TypeError as e:
        # 双重保险：签名检测失败时回退
        if "det_batch_size" in pp_kwargs or "rec_batch_size" in pp_kwargs:
            pp_kwargs.pop("det_batch_size", None)
            pp_kwargs.pop("rec_batch_size", None)
            print(f"[WARNING] PPStructureV3 不支持 batch size 参数 ({e})，使用默认值")
            return PPStructureV3(**pp_kwargs)
        raise


def get_ppstructure() -> Any:
    """
    获取单例 PP-StructureV3 实例（避免重复初始化）。

    Returns:
        PPStructureV3 实例
    """
    global _pipeline_cache, _pipeline_init_error
    if _pipeline_cache is not None:
        return _pipeline_cache
    if _pipeline_init_error is not None:
        raise _pipeline_init_error

    # Thread-safe lazy init: avoid racing multiple PPStructureV3 initializations
    # under FastAPI/uvicorn concurrency within a single process.
    with _pipeline_lock:
        if _pipeline_cache is not None:
            return _pipeline_cache
        if _pipeline_init_error is not None:
            raise _pipeline_init_error
        try:
            _pipeline_cache = _create_ppstructure()
        except BaseException as e:
            _pipeline_init_error = e
            raise
    return _pipeline_cache


def warmup_ppstructure() -> None:
    """
    Pre-load PP-StructureV3 weights and run a small inference once.

    Use a page-like synthetic image (text-like strokes + table grid) to increase
    the chance of triggering lazy init for common branches.
    """
    pipeline = get_ppstructure()

    import tempfile
    from PIL import Image, ImageDraw

    tmp_path: Optional[Path] = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            tmp_path = Path(f.name)

        # Synthetic page-like image: some text strokes + a simple table grid.
        w, h = 800, 1100
        img = Image.new("RGB", (w, h), color=(255, 255, 255))
        draw = ImageDraw.Draw(img)

        # Text-like strokes
        y = 80
        while y < 240:
            draw.rectangle([80, y, 700, y + 6], fill=(0, 0, 0))
            y += 24

        # Table-like grid (helps trigger table branch when enabled)
        x0, y0 = 100, 320
        x1, y1 = 700, 620
        cols, rows = 4, 5
        for i in range(cols + 1):
            x = int(x0 + (x1 - x0) * i / cols)
            draw.line([x, y0, x, y1], fill=(0, 0, 0), width=3)
        for j in range(rows + 1):
            yy = int(y0 + (y1 - y0) * j / rows)
            draw.line([x0, yy, x1, yy], fill=(0, 0, 0), width=3)

        img.save(tmp_path)
        pipeline.predict(str(tmp_path))
    finally:
        if tmp_path is not None:
            try:
                tmp_path.unlink()
            except OSError:
                pass


def layout_blocks_from_doc(doc: dict[str, Any]) -> list[dict[str, Any]]:
    """
    将 PP-StructureV3 parsing_res_list 转换为标准化的 block 字典列表。

    Args:
        doc: PP-StructureV3 predict 返回的文档对象

    Returns:
        标准化的版面块列表，每个块包含 index, label, region_label, bbox, content
    """
    blocks: list[dict[str, Any]] = []

    parsing_list = doc.get("parsing_res_list") or []
    for blk in parsing_list:
        # blk is a LayoutBlock object
        if hasattr(blk, "to_dict"):
            info = blk.to_dict()
        else:
            info = getattr(blk, "__dict__", {})

        if not info:
            continue

        label = info.get("label")
        bbox = info.get("bbox")
        content = info.get("content", "")

        if not bbox or label is None:
            continue

        blocks.append(
            {
                "index": info.get("index", 0),
                "label": label,
                "region_label": info.get("region_label"),
                "bbox": bbox,
                "content": content if isinstance(content, str) else str(content),
            }
        )

    # 按阅读顺序排序（index, 然后 top y, 然后 left x）
    blocks.sort(key=lambda b: (b["index"], b["bbox"][1], b["bbox"][0]))
    return blocks
