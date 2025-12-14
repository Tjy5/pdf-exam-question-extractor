"""
parallel_extraction.py - 页面级并发OCR处理模块

使用ThreadPoolExecutor实现页面级并发，通过Semaphore串行化GPU推理，
避免在小显存GPU（如6GB）上发生显存溢出。

设计要点：
- 共享单个PP-StructureV3实例（避免显存复制）
- GPU推理串行化（Semaphore(1)）
- CPU预处理/后处理可并发执行
- 实时进度回调
- 使用上下文管理器确保资源及时释放
"""
from __future__ import annotations

import json
import logging
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from queue import Queue
from threading import Semaphore
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


class _GpuLockedPipeline:
    """包装 pipeline，仅在 predict 调用时获取 GPU 锁。"""

    __slots__ = ("_pipeline", "_sem", "_log", "_page")

    def __init__(
        self,
        pipeline: Any,
        sem: Semaphore,
        log_fn: Callable[[str], None],
        page_name: str,
    ) -> None:
        self._pipeline = pipeline
        self._sem = sem
        self._log = log_fn
        self._page = page_name

    def predict(self, *args: Any, **kwargs: Any) -> Any:
        with self._sem:
            self._log(f"  [OCR] {self._page} (GPU推理中...)")
            return self._pipeline.predict(*args, **kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._pipeline, name)


class ParallelPageProcessor:
    """页面级并发OCR处理器，支持GPU串行化。"""

    def __init__(
        self,
        max_workers: int = 4,
        pipeline: Any = None,
        gpu_semaphore: Optional[Semaphore] = None,
    ) -> None:
        """
        初始化并发处理器。

        Args:
            max_workers: 最大并发worker数量（默认4）
            pipeline: 共享的PP-StructureV3实例（必须提供）
            gpu_semaphore: GPU推理信号量（默认Semaphore(1)）
        """
        self.max_workers = max_workers
        self.pipeline = pipeline
        self._gpu_semaphore = gpu_semaphore or Semaphore(1)
        self._prefetch_size = get_prefetch_size()
        self._extract_fn: Optional[Callable] = None
        self._save_fn: Optional[Callable] = None
        self._is_valid_meta_fn: Optional[Callable] = None

    def set_extraction_functions(
        self,
        extract_fn: Callable,
        save_fn: Callable,
        is_valid_meta_fn: Callable,
    ) -> None:
        """
        设置提取和保存函数（避免循环导入）。

        Args:
            extract_fn: extract_questions_from_page函数
            save_fn: save_questions_for_page函数
            is_valid_meta_fn: is_valid_meta函数
        """
        self._extract_fn = extract_fn
        self._save_fn = save_fn
        self._is_valid_meta_fn = is_valid_meta_fn

    def process_pages_parallel(
        self,
        img_paths: List[Path],
        base_output_dir: Path,
        skip_existing: bool = False,
        progress_callback: Optional[Callable[[int, int, str, str], None]] = None,
        log: Optional[Callable[[str], None]] = None,
    ) -> List[Dict[str, Any]]:
        """
        并发处理多个页面图片。

        Args:
            img_paths: 页面图片路径列表（已排序）
            base_output_dir: 输出目录
            skip_existing: 是否跳过已存在的有效结果
            progress_callback: 进度回调函数 (done, total, status, page_name)
            log: 日志输出函数

        Returns:
            按页面顺序排列的处理结果列表
        """
        if self.pipeline is None:
            raise ValueError("pipeline must be provided (shared GPU model instance)")
        if self._extract_fn is None or self._save_fn is None:
            raise ValueError("extraction functions not set, call set_extraction_functions first")

        total_pages = len(img_paths)
        if total_pages == 0:
            return []

        logger_fn = log or (lambda m: logger.info(m))
        base_output_dir = Path(base_output_dir)
        base_output_dir.mkdir(parents=True, exist_ok=True)

        # 结果数组，按页面索引存储
        results: List[Optional[Dict[str, Any]]] = [None] * total_pages
        completed = 0

        logger_fn(f"[并发] 启动 {self.max_workers} 个worker处理 {total_pages} 页 (预取队列: {self._prefetch_size})")

        # 预取队列与生产者线程
        queue: Queue[Any] = Queue(maxsize=self._prefetch_size)
        stop_event = threading.Event()
        sentinel = object()

        producer = threading.Thread(
            target=self._prefetch_producer,
            args=(img_paths, queue, stop_event, logger_fn, sentinel),
            name="prefetch-producer",
            daemon=True,
        )
        producer.start()

        results_lock = threading.Lock()

        def worker() -> None:
            nonlocal completed
            while True:
                item = queue.get()
                try:
                    if item is sentinel:
                        return

                    idx, img_path = item
                    page_name = img_path.stem

                    try:
                        result = self._process_single_page(
                            idx,
                            img_path,
                            base_output_dir,
                            skip_existing,
                            logger_fn,
                            base_output_dir,
                        )
                        status = result.get("status", "unknown")
                    except Exception as exc:
                        logger.exception("页面 %s 处理异常: %s", page_name, exc)
                        result = {
                            "page_index": idx,
                            "page_name": page_name,
                            "status": "error",
                            "error": str(exc),
                        }
                        status = "error"

                    with results_lock:
                        results[idx] = result
                        completed += 1
                        done = completed

                    if progress_callback:
                        try:
                            progress_callback(done, total_pages, status, page_name)
                        except Exception as cb_exc:
                            logger.warning("进度回调异常: %s", cb_exc)
                finally:
                    queue.task_done()

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            for _ in range(self.max_workers):
                executor.submit(worker)

            queue.join()
            stop_event.set()
            producer.join(timeout=5)

        logger_fn(f"[并发] 完成 {completed}/{total_pages} 页处理")

        # 过滤None并按页面顺序返回
        return [res for res in results if res is not None]

    def _process_single_page(
        self,
        page_index: int,
        img_path: Path,
        base_output_dir: Path,
        skip_existing: bool,
        log: Callable[[str], None],
        workdir: Optional[Path] = None,
    ) -> Dict[str, Any]:
        """
        处理单个页面（带GPU串行化）。

        Args:
            page_index: 页面索引
            img_path: 页面图片路径
            base_output_dir: 输出目录
            skip_existing: 是否跳过已存在的有效结果
            log: 日志输出函数

        Returns:
            处理结果字典
        """
        page_name = img_path.stem
        meta_path = base_output_dir / f"questions_{page_name}" / "meta.json"

        # 检查是否可以跳过
        if skip_existing and self._is_valid_meta_fn and self._is_valid_meta_fn(meta_path):
            try:
                with meta_path.open("r", encoding="utf-8") as fh:
                    meta = json.load(fh)
                log(f"  [跳过] {page_name} (已存在有效结果)")
                return {
                    "page_index": page_index,
                    "page_name": page_name,
                    "status": "skipped",
                    "summary": meta,
                }
            except Exception as exc:
                logger.warning("无法复用 %s 的meta (%s)，重新处理", img_path, exc)

        questions: Optional[List[Dict[str, Any]]] = None
        try:
            # 使用包装器将 GPU 临界区缩小到 predict 调用
            # 图片加载/预处理可在等待 GPU 锁时并行执行
            wrapped_pipeline = _GpuLockedPipeline(
                self.pipeline, self._gpu_semaphore, log, page_name
            )
            questions = self._extract_fn(img_path, wrapped_pipeline, workdir=workdir)

            # CPU后处理（可并发）
            if not questions:
                log(f"  [空页] {page_name} (未检测到题目)")

            summary = self._save_fn(
                img_path=img_path,
                questions=questions or [],
                base_output_dir=base_output_dir,
            )

            return {
                "page_index": page_index,
                "page_name": page_name,
                "status": "success",
                "question_count": len(questions) if questions else 0,
                "summary": summary,
            }

        except Exception as exc:
            logger.exception("处理页面 %s 失败: %s", page_name, exc)
            return {
                "page_index": page_index,
                "page_name": page_name,
                "status": "error",
                "error": str(exc),
            }

    def _prefetch_producer(
        self,
        img_paths: List[Path],
        queue: Queue[Any],
        stop_event: threading.Event,
        log: Callable[[str], None],
        sentinel: Any,
    ) -> None:
        """
        生产者：预取图片触发文件系统缓存，减少 GPU 等待时间。

        将 (idx, img_path) 放入有界队列，末尾发送 sentinel 终止信号。
        """
        try:
            for idx, img_path in enumerate(img_paths):
                if stop_event.is_set():
                    break
                try:
                    # 轻量读取触发文件系统缓存
                    with img_path.open("rb") as f:
                        f.read(4096)
                except Exception as exc:
                    log(f"[WARN] 预取 {img_path.name} 时出错: {exc}")

                queue.put((idx, img_path))
        finally:
            # 发送终止信号，数量=worker数
            for _ in range(self.max_workers):
                queue.put(sentinel)


def get_default_max_workers() -> int:
    """
    获取默认的worker数量。

    优先使用环境变量EXAMPAPER_MAX_WORKERS，否则根据CPU核心数计算。
    考虑到GPU串行化，worker数量不宜过多（建议4-6）。
    """
    env_workers = os.getenv("EXAMPAPER_MAX_WORKERS", "").strip()
    if env_workers.isdigit():
        return max(1, min(int(env_workers), 8))

    # 默认使用CPU核心数的一半，最少2个，最多6个
    try:
        cpu_count = os.cpu_count() or 4
        return max(2, min(cpu_count // 2, 6))
    except Exception:
        return 4


def get_prefetch_size() -> int:
    """获取预取队列大小（默认8，受环境变量 EXAMPAPER_PREFETCH_SIZE 控制）。"""
    raw = os.getenv("EXAMPAPER_PREFETCH_SIZE", "").strip()
    if raw.isdigit():
        return max(1, min(int(raw), 64))
    return 8


def is_parallel_extraction_enabled() -> bool:
    """检查是否启用并发提取。"""
    return os.getenv("EXAMPAPER_PARALLEL_EXTRACTION", "0") == "1"
