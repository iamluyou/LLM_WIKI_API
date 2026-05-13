"""LLM 调用封装，OpenAI 兼容协议"""

import asyncio
import logging
from typing import Optional

from openai import OpenAI

from app.config import settings

logger = logging.getLogger(__name__)


class LLMClient:
    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
    ):
        self.api_key = api_key or settings.llm_api_key
        self.base_url = base_url or settings.llm_base_url
        self.model = model or settings.llm_model
        self.client = OpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
        )

    def chat(
        self,
        messages: list[dict],
        max_tokens: int = 16000,
        temperature: float = 0.3,
    ) -> tuple[str, dict]:
        """调用 LLM，返回 (response_text, usage_stats)"""
        msg_count = len(messages)
        logger.info(f"[LLM] Calling {self.model} with {msg_count} messages, max_tokens={max_tokens}")
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
            )
            text = response.choices[0].message.content or ""
            usage = {
                "input": getattr(response.usage, "prompt_tokens", 0) or 0,
                "output": getattr(response.usage, "completion_tokens", 0) or 0,
            }
            logger.info(f"[LLM] Response received: {len(text)} chars, tokens={usage}")
            return text, usage
        except Exception as e:
            logger.error(f"[LLM] Call failed: {e}")
            raise

    async def achat(
        self,
        messages: list[dict],
        max_tokens: int = 16000,
        temperature: float = 0.3,
    ) -> tuple[str, dict]:
        """异步调用 LLM（在线程池中执行同步调用，避免阻塞事件循环）"""
        return await asyncio.to_thread(self.chat, messages, max_tokens, temperature)

    def chat_stream(self, messages: list[dict], max_tokens: int = 16000, temperature: float = 0.3):
        """流式调用 LLM"""
        try:
            stream = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
                stream=True,
            )
            for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content
        except Exception as e:
            logger.error(f"LLM stream call failed: {e}")
            raise


# 单例
llm_client = LLMClient()
