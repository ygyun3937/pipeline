"""Anthropic API를 직접 사용하는 LLM 클라이언트."""
from __future__ import annotations

import anthropic

from src.logger import get_logger

logger = get_logger(__name__)


class AnthropicClient:
    """Anthropic API를 직접 호출하는 클라이언트 (ANTHROPIC_API_KEY 필요)."""

    def __init__(self, api_key: str, model: str = "claude-sonnet-4-6") -> None:
        self._model = model
        self._client = anthropic.AsyncAnthropic(api_key=api_key)
        logger.info("AnthropicClient 초기화: model=%s", model)

    @property
    def model_name(self) -> str:
        return self._model

    async def complete(self, system_prompt: str, user_message: str) -> str:
        message = await self._client.messages.create(
            model=self._model,
            max_tokens=4096,
            system=system_prompt,
            messages=[{"role": "user", "content": user_message}],
        )
        return message.content[0].text
