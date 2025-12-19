"""
AI Services Module

提供 AI 模型交互的统一接口
"""

from .base import (
    AIProvider,
    ChatMessage,
    StreamChunk,
    AIProviderError,
    AIProviderConnectionError,
    AIProviderRateLimitError,
    AIProviderAuthError,
)
from .openai_compatible import OpenAICompatibleProvider
from .mock_provider import MockProvider
from .prompts import (
    build_analyze_prompt,
    build_similar_prompt,
    build_reanswer_prompt,
)
from .parser import (
    AnalyzeResult,
    parse_analyze_response,
)

__all__ = [
    # Base
    "AIProvider",
    "ChatMessage",
    "StreamChunk",
    "AIProviderError",
    "AIProviderConnectionError",
    "AIProviderRateLimitError",
    "AIProviderAuthError",
    # Providers
    "OpenAICompatibleProvider",
    "MockProvider",
    # Prompts
    "build_analyze_prompt",
    "build_similar_prompt",
    "build_reanswer_prompt",
    # Parser
    "AnalyzeResult",
    "parse_analyze_response",
]
