"""
Performance monitoring and tracing module.

提供轻量级性能监控，支持：
- 结构化日志输出（JSON格式）
- 可选的trace文件持久化
- 采样率控制（避免生产环境性能影响）
- 线程安全

Environment variables:
- EXAMPAPER_PERF_LOG: 启用性能日志（1=启用）
- EXAMPAPER_PERF_TRACE: trace文件路径（启用则写入jsonl）
- EXAMPAPER_PERF_SAMPLE_RATE: 采样率，默认1.0（100%）
"""

from __future__ import annotations

import json
import logging
import os
import random
import threading
import time
from contextlib import contextmanager
from functools import lru_cache
from typing import Any, Dict, Iterator, Optional

_logger = logging.getLogger("exampaper.perf")
_trace_lock = threading.Lock()


def _env_flag(name: str, default: str = "0") -> bool:
    """Parse boolean environment variable."""
    return os.getenv(name, default).strip() == "1"


def _env_float(name: str, default: float) -> float:
    """Parse float environment variable with validation."""
    raw = (os.getenv(name, "") or "").strip()
    if not raw:
        return default
    try:
        val = float(raw)
        return val if val > 0 else default
    except ValueError:
        return default


@lru_cache(maxsize=1)
def _perf_config() -> tuple[bool, Optional[str], float]:
    """
    Get performance monitoring configuration (cached).

    Returns:
        (enabled, trace_path, sample_rate)
    """
    trace_path = (os.getenv("EXAMPAPER_PERF_TRACE") or "").strip() or None
    enabled = _env_flag("EXAMPAPER_PERF_LOG", "0") or bool(trace_path)
    sample_rate = _env_float("EXAMPAPER_PERF_SAMPLE_RATE", 1.0)
    if sample_rate > 1.0:
        sample_rate = 1.0
    return enabled, trace_path, sample_rate


def perf_enabled() -> bool:
    """Check if performance monitoring is enabled."""
    enabled, _, _ = _perf_config()
    return enabled


def perf_event(name: str, **fields: Any) -> None:
    """
    Log a performance event with structured fields.

    Args:
        name: Event name (e.g., "ocr.predict", "page.save")
        **fields: Additional structured fields
    """
    enabled, trace_path, sample_rate = _perf_config()
    if not enabled:
        return

    # Apply sampling rate (for high-frequency events)
    if sample_rate < 1.0 and random.random() > sample_rate:
        return

    payload: Dict[str, Any] = {
        "ts": time.time(),
        "name": name,
        "pid": os.getpid(),
        "thread": threading.get_ident(),
        **fields,
    }

    # Compact JSON format for better performance
    line = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    _logger.info("%s", line)

    # Write to trace file if configured
    if trace_path:
        try:
            with _trace_lock:
                with open(trace_path, "a", encoding="utf-8") as f:
                    f.write(line + "\n")
        except OSError:
            # Best-effort only, don't crash on I/O errors
            pass


@contextmanager
def perf_span(name: str, **fields: Any) -> Iterator[None]:
    """
    Context manager for timing a code block.

    Usage:
        with perf_span("my_operation", page="page_1"):
            # ... do work ...

    This will automatically log the elapsed time in milliseconds.

    Args:
        name: Span name
        **fields: Additional structured fields
    """
    if not perf_enabled():
        yield
        return

    t0 = time.perf_counter()
    try:
        yield
    finally:
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        perf_event(name, ms=round(elapsed_ms, 3), **fields)
