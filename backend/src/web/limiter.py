"""
Rate Limiter - SlowAPI configuration for API rate limiting
"""
from __future__ import annotations

from typing import Any, Callable

try:
    from slowapi import Limiter
    from slowapi.util import get_remote_address
except ImportError:  # pragma: no cover
    Limiter = None  # type: ignore[assignment]
    get_remote_address = None  # type: ignore[assignment]


class _NoopLimiter:
    enabled = False

    def limit(self, _: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
            return func

        return decorator


if Limiter is None or get_remote_address is None:
    limiter = _NoopLimiter()
else:
    limiter = Limiter(key_func=get_remote_address, default_limits=["60/minute"])
    limiter.enabled = True  # type: ignore[attr-defined]
