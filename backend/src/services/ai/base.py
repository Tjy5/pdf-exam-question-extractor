"""
AI Provider 抽象接口

定义了 AI 模型交互的统一协议，支持多种 AI 提供商（OpenAI、DeepSeek、Ollama 等）
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import AsyncIterator, Protocol, Optional, Dict, Any, Union, List


@dataclass
class ChatMessage:
    """聊天消息"""
    role: str  # "system" | "user" | "assistant"
    # OpenAI-compatible APIs allow multimodal "content" as a list of blocks (text, image_url, etc.).
    # Keep string support for existing callers.
    content: Union[str, List[Dict[str, Any]]]


@dataclass
class StreamChunk:
    """流式响应片段"""
    content: str
    finish_reason: Optional[str] = None


class AIProvider(Protocol):
    """AI 提供商协议

    所有 AI 模型实现必须遵循此接口，确保可互换性
    """

    async def stream_chat(
        self,
        messages: list[ChatMessage],
        *,
        model: str,
        temperature: float = 0.7,
        max_tokens: int = 2000,
        **kwargs: Any
    ) -> AsyncIterator[StreamChunk]:
        """
        流式生成聊天回复

        Args:
            messages: 对话历史
            model: 模型名称
            temperature: 温度参数（0.0-2.0，越高越随机）
            max_tokens: 最大生成 token 数
            **kwargs: 其他特定于提供商的参数

        Yields:
            StreamChunk: 增量文本片段

        Raises:
            AIProviderError: AI 调用失败
        """
        ...


class AIProviderError(Exception):
    """AI Provider 错误基类"""
    pass


class AIProviderConnectionError(AIProviderError):
    """连接错误"""
    pass


class AIProviderRateLimitError(AIProviderError):
    """速率限制错误"""
    pass


class AIProviderAuthError(AIProviderError):
    """认证错误"""
    pass
