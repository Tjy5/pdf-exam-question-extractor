"""
Step Registry - Dynamic step registration and discovery.

This module provides a registry for pipeline steps, enabling:
- Decorator-based step registration
- Dynamic step ordering
- Conditional step inclusion
- Plugin-style extensibility
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, TypeVar

from .contracts import StepName
from .steps.base import StepExecutor

StepFactory = Callable[..., StepExecutor]
T = TypeVar("T", bound=StepFactory)


class StepRegistry:
    """
    Registry for pipeline step factories.

    Steps are registered with a name and optional order. The registry
    maintains the execution order and provides factory lookup.

    Usage:
        @StepRegistry.register("pdf_to_images", order=0)
        def create_pdf_to_images_step(**kwargs) -> StepExecutor:
            return PdfToImagesStep(**kwargs)

        # Later, get all steps in order
        factories = StepRegistry.get_ordered_factories()
        steps = [f(**config) for f in factories]
    """

    _factories: Dict[str, StepFactory] = {}
    _order: Dict[str, int] = {}
    _metadata: Dict[str, Dict[str, Any]] = {}
    _initialized: bool = False

    @classmethod
    def register(
        cls,
        name: str,
        *,
        order: int = -1,
        critical: bool = False,
        description: str = "",
    ) -> Callable[[T], T]:
        """
        Decorator to register a step factory.

        Args:
            name: Step name (should match StepName enum value)
            order: Execution order (lower = earlier). -1 means append to end.
            critical: If True, pipeline fails on step failure
            description: Human-readable description

        Returns:
            Decorator function
        """

        def decorator(factory: T) -> T:
            # Idempotent: skip if already registered with same factory
            if name in cls._factories:
                if cls._factories[name] is factory:
                    return factory
                raise ValueError(f"Step '{name}' already registered with different factory")

            cls._factories[name] = factory
            cls._order[name] = order if order >= 0 else len(cls._factories) * 10
            cls._metadata[name] = {
                "critical": critical,
                "description": description,
            }
            return factory

        return decorator

    @classmethod
    def get(cls, name: str) -> Optional[StepFactory]:
        """Get a step factory by name."""
        return cls._factories.get(name)

    @classmethod
    def get_ordered_names(cls) -> List[str]:
        """Get step names in execution order."""
        return sorted(cls._factories.keys(), key=lambda n: cls._order.get(n, 999))

    @classmethod
    def get_ordered_factories(cls) -> List[StepFactory]:
        """Get step factories in execution order."""
        return [cls._factories[name] for name in cls.get_ordered_names()]

    @classmethod
    def get_metadata(cls, name: str) -> Dict[str, Any]:
        """Get metadata for a step."""
        return cls._metadata.get(name, {})

    @classmethod
    def is_critical(cls, name: str) -> bool:
        """Check if a step is critical (pipeline fails on step failure)."""
        return cls._metadata.get(name, {}).get("critical", False)

    @classmethod
    def list_all(cls) -> List[Dict[str, Any]]:
        """List all registered steps with metadata."""
        return [
            {
                "name": name,
                "order": cls._order.get(name, 999),
                **cls._metadata.get(name, {}),
            }
            for name in cls.get_ordered_names()
        ]

    @classmethod
    def clear(cls) -> None:
        """Clear all registrations (mainly for testing)."""
        cls._factories.clear()
        cls._order.clear()
        cls._metadata.clear()
        cls._initialized = False


def register_default_steps() -> None:
    """
    Register the default pipeline steps.

    This function is called during module initialization to register
    the standard 5-step pipeline. Custom steps can be registered
    before or after calling this function.

    This function is idempotent - calling it multiple times has no effect.
    """
    if StepRegistry._initialized:
        return
    StepRegistry._initialized = True

    from .steps import (
        create_analyze_data_step,
        create_collect_results_step,
        create_compose_long_image_step,
        create_extract_questions_step,
        create_pdf_to_images_step,
    )

    StepRegistry.register(
        StepName.pdf_to_images.value,
        order=0,
        critical=True,
        description="将 PDF 每一页转换为高分辨率图像",
    )(create_pdf_to_images_step)

    StepRegistry.register(
        StepName.extract_questions.value,
        order=10,
        critical=True,
        description="使用 PP-StructureV3 识别版面结构并缓存",
    )(create_extract_questions_step)

    StepRegistry.register(
        StepName.analyze_data.value,
        order=20,
        critical=False,
        description="分析题目边界，检测资料分析区域",
    )(create_analyze_data_step)

    StepRegistry.register(
        StepName.compose_long_image.value,
        order=30,
        critical=False,
        description="裁剪题目图片，跨页内容智能拼接",
    )(create_compose_long_image_step)

    StepRegistry.register(
        StepName.collect_results.value,
        order=40,
        critical=True,
        description="验证输出完整性，生成汇总信息",
    )(create_collect_results_step)


# Auto-register default steps on module import
register_default_steps()
