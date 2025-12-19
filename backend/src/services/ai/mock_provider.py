"""
Mock AI Provider

用于开发和测试，模拟 AI 回复
"""

from __future__ import annotations

import asyncio
from typing import AsyncIterator, Optional, Any

from .base import ChatMessage, StreamChunk


class MockProvider:
    """Mock AI 提供商（用于开发测试）"""

    def _message_text(self, msg: ChatMessage) -> str:
        content = msg.content
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if not isinstance(item, dict):
                    continue
                if item.get("type") == "text" and isinstance(item.get("text"), str):
                    parts.append(item["text"])
            return "\n".join(parts).strip()
        return str(content)

    async def stream_chat(
        self,
        messages: list[ChatMessage],
        *,
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 2000,
        **kwargs: Any
    ) -> AsyncIterator[StreamChunk]:
        """
        模拟流式回复

        返回一个模拟的解析回答
        """
        # 提取最后一条用户消息
        last_user_message = ""
        for msg in reversed(messages):
            if msg.role == "user":
                last_user_message = self._message_text(msg)
                break

        # 模拟回复内容
        mock_response = f"""【模拟 AI 解析】

您的问题是：{last_user_message}

这是一个模拟的答复。真实环境下，这里将显示 AI 模型生成的详细解析。

**题目考点分析：**
- 这道题考查的是xxx知识点
- 需要掌握xxx技巧

**正确答案推理：**
1. 首先观察题干特征
2. 然后分析各选项
3. 最后得出结论

**常见错误陷阱：**
- 错误选项A：迷惑点在于xxx
- 错误选项B：容易忽略xxx

**解题技巧：**
记住口诀："xxx"，遇到此类题型优先考虑xxx。

---
*提示：这是Mock Provider的测试回复，配置真实AI模型后将显示真实内容*
"""

        # 模拟逐字流式输出
        words = mock_response.split()
        for i, word in enumerate(words):
            await asyncio.sleep(0.05)  # 模拟网络延迟
            yield StreamChunk(
                content=word + (" " if i < len(words) - 1 else ""),
                finish_reason="stop" if i == len(words) - 1 else None
            )
