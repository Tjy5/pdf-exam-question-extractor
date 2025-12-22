"""
OpenAI 兼容 Provider

支持所有实现 OpenAI API 格式的服务商（OpenAI、DeepSeek、Moonshot、本地模型等）
"""

from __future__ import annotations

import html
import json
from typing import AsyncIterator, Optional, Dict, Any
import httpx

from .base import (
    AIProvider,
    ChatMessage,
    StreamChunk,
    AIProviderError,
    AIProviderConnectionError,
    AIProviderRateLimitError,
    AIProviderAuthError,
)


class OpenAICompatibleProvider:
    """OpenAI API 兼容的提供商实现"""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        default_model: str = "gpt-3.5-turbo",
        timeout: float = 60.0
    ):
        """
        初始化 OpenAI 兼容提供商

        Args:
            base_url: API 基础 URL（例如：https://api.openai.com/v1）
            api_key: API 密钥
            default_model: 默认模型名称
            timeout: 请求超时时间（秒）
        """
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.default_model = default_model
        self.timeout = timeout

    async def close(self):
        """保留接口（当前实现为按请求创建 client，无需显式关闭）"""
        pass

    async def stream_chat(
        self,
        messages: list[ChatMessage],
        *,
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 2000,
        top_p: Optional[float] = None,
        response_format: Optional[Dict[str, Any]] = None,
        thinking: Optional[Dict[str, Any]] = None,
        tools: Optional[list[Dict[str, Any]]] = None,
        tool_choice: Optional[Any] = None,
        stream_options: Optional[Dict[str, Any]] = None,
        **kwargs: Any
    ) -> AsyncIterator[StreamChunk]:
        """
        流式生成聊天回复

        支持所有 OpenAI Chat Completions API 兼容的服务（包含 Gemini 3 Pro 扩展）
        """
        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

        # 构建基础 payload
        payload = {
            "model": model or self.default_model,
            "messages": [{"role": msg.role, "content": msg.content} for msg in messages],
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True
        }

        # 只在显式传递时才添加 top_p（某些API代理不支持此参数）
        if top_p is not None:
            payload["top_p"] = top_p

        # 添加其他可选参数
        if response_format is not None:
            payload["response_format"] = response_format
        if thinking is not None:
            payload["thinking"] = thinking
        if tools is not None:
            payload["tools"] = tools
        if tool_choice is not None:
            payload["tool_choice"] = tool_choice
        if stream_options is not None:
            payload["stream_options"] = stream_options

        # 添加其他 kwargs（但排除已知的不兼容参数）
        for key, value in kwargs.items():
            if key not in payload:
                payload[key] = value

        try:
            # 优化超时配置：允许长时间"思考"，但设置合理上限防止无限挂起
            timeout = httpx.Timeout(
                connect=10.0,
                read=1800.0,  # 30 分钟最大读取时间（思考模式）
                write=60.0,
                pool=60.0
            )

            # 记录请求参数（调试用）
            import logging
            logger = logging.getLogger(__name__)

            # Do not inherit system proxy env vars (HTTP_PROXY/HTTPS_PROXY), which can break
            # outbound calls in some dev environments.
            async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
                async with client.stream("POST", url, headers=headers, json=payload) as response:
                    if response.status_code != 200:
                        error_bytes = await response.aread()
                        error_preview = error_bytes[:8192].decode("utf-8", errors="replace")

                        # 记录完整错误信息
                        logger.error(f"[OpenAI API] Request failed with status {response.status_code}")
                        logger.error(f"[OpenAI API] Request payload: {json.dumps({k: v for k, v in payload.items() if k != 'messages'}, ensure_ascii=False)}")
                        logger.error(f"[OpenAI API] Error response: {error_preview}")

                        msg = f"API request failed with status {response.status_code}: {error_preview}"

                        if response.status_code in (401, 403):
                            raise AIProviderAuthError(msg)
                        if response.status_code == 429:
                            raise AIProviderRateLimitError(msg)
                        raise AIProviderError(msg)

                    event_data_lines: list[str] = []

                    def _flush_sse_event(data_str: str) -> Optional[tuple[Optional[dict[str, Any]], bool]]:
                        cleaned = data_str.strip()
                        if not cleaned:
                            return None
                        if cleaned == "[DONE]":
                            return None, True
                        try:
                            return json.loads(cleaned), False
                        except json.JSONDecodeError:
                            return None

                    _debug_chunk_count = 0

                    def _iter_chunks_from_data(data: dict[str, Any]):
                        nonlocal _debug_chunk_count
                        choices = data.get("choices", [])
                        if not isinstance(choices, list) or not choices:
                            return
                        for choice in choices:
                            _debug_chunk_count += 1
                            if not isinstance(choice, dict):
                                continue
                            delta = choice.get("delta") or {}
                            if not isinstance(delta, dict):
                                delta = {}
                            # Some providers may return content in "message" for JSON-line streams
                            if not delta and isinstance(choice.get("message"), dict):
                                delta = choice.get("message") or {}

                            reasoning_keys = (
                                "reasoning_content",
                                "reasoning",
                                "thinking",
                                "thoughts",
                                "reasoning_details",
                                "thought",
                                "internal_monologue",
                                "internal_thoughts",
                                "chain_of_thought",
                            )
                            reasoning_content: Optional[str] = None
                            for key in reasoning_keys:
                                value = delta.get(key)
                                if isinstance(value, str) and value:
                                    reasoning_content = value
                                    break
                                if value is not None and _debug_chunk_count <= 5:
                                    logger.debug(
                                        f"[OpenAI API] Non-string reasoning field: {key} type={type(value).__name__}"
                                    )
                            if reasoning_content is None and _debug_chunk_count <= 5:
                                candidate_keys = []
                                for key in delta.keys():
                                    if key in reasoning_keys or key == "content":
                                        continue
                                    lowered = key.lower()
                                    if any(tok in lowered for tok in ("reason", "think", "thought", "chain", "monologue")):
                                        candidate_keys.append(key)
                                if candidate_keys:
                                    logger.debug(
                                        f"[OpenAI API] Unmapped reasoning-like fields in delta: {candidate_keys}"
                                    )
                            if isinstance(reasoning_content, str) and reasoning_content:
                                logger.debug(f"[OpenAI API] Found reasoning content: {reasoning_content[:50]}...")
                                yield StreamChunk(content=reasoning_content, finish_reason=None, kind="reasoning")

                            content = delta.get("content")
                            if isinstance(content, str) and content:
                                logger.debug(f"[OpenAI API] Found content: {content[:50]}...")
                                yield StreamChunk(content=content, finish_reason=None)

                            finish_reason = choice.get("finish_reason")
                            if finish_reason:
                                yield StreamChunk(content="", finish_reason=str(finish_reason))
                                return

                    async for line in response.aiter_lines():
                        # SSE 事件边界：空行或仅包含空格的行结束一个事件
                        if not line.strip():
                            if not event_data_lines:
                                continue

                            data_str = "\n".join(event_data_lines)
                            event_data_lines.clear()

                            flushed = _flush_sse_event(data_str)
                            if flushed is None:
                                continue
                            data_or_none, done = flushed
                            if done:
                                break
                            if data_or_none is None:
                                continue

                            data = data_or_none
                            for chunk in _iter_chunks_from_data(data):
                                yield chunk

                            continue

                        # SSE data 行：接受 "data:" 或 "data: "
                        if line.startswith("data:"):
                            event_data_lines.append(line[5:].lstrip())
                            continue

                        # Fallback: some providers stream JSON lines without SSE "data:" prefix
                        cleaned = line.strip()
                        if cleaned.startswith("{") and cleaned.endswith("}"):
                            try:
                                data = json.loads(cleaned)
                                for chunk in _iter_chunks_from_data(data):
                                    yield chunk
                            except json.JSONDecodeError:
                                continue

                    # 处理流结束时未被空行终止的最后一个事件
                    if event_data_lines:
                        data_str = "\n".join(event_data_lines)
                        flushed = _flush_sse_event(data_str)
                        if flushed and flushed[0]:
                            data = flushed[0]
                            for chunk in _iter_chunks_from_data(data):
                                yield chunk

        except httpx.TimeoutException as e:
            raise AIProviderConnectionError(f"Request timeout: {e}")
        except httpx.RequestError as e:
            raise AIProviderConnectionError(f"Connection error: {e}")
        except Exception as e:
            if not isinstance(e, AIProviderError):
                raise AIProviderError(f"Unexpected error: {e}")
            raise
