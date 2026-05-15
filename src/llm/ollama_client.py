from __future__ import annotations

from collections.abc import AsyncIterator

from openai import AsyncOpenAI

from src.llm.base import ChatTurn
from src.logger import get_logger

logger = get_logger(__name__)


class OllamaClient:
    """Ollama OpenAI 호환 API를 사용하는 LLM 클라이언트 (폐쇄망 환경)."""

    def __init__(self, base_url: str, model: str) -> None:
        self._model = model
        self._openai = AsyncOpenAI(
            base_url=f"{base_url.rstrip('/')}/v1",
            api_key="ollama",  # Ollama는 인증 불필요, 더미값
        )
        logger.info("OllamaClient 초기화: base_url=%s, model=%s", base_url, model)

    @property
    def model_name(self) -> str:
        return self._model

    async def complete(self, system_prompt: str, user_message: str) -> str:
        resp = await self._openai.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
        )
        return resp.choices[0].message.content or ""

    async def stream(self, system_prompt: str, user_message: str) -> AsyncIterator[str]:  # type: ignore[override]
        resp = await self._openai.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            stream=True,
        )
        async for chunk in resp:
            delta = chunk.choices[0].delta.content
            if delta:
                yield delta

    async def complete_with_history(
        self,
        system_prompt: str,
        history: list[ChatTurn],
        user_message: str,
    ) -> str:
        messages = [{"role": "system", "content": system_prompt}]
        messages.extend({"role": t["role"], "content": t["content"]} for t in history)
        messages.append({"role": "user", "content": user_message})
        resp = await self._openai.chat.completions.create(model=self._model, messages=messages)
        return resp.choices[0].message.content or ""

    async def stream_with_history(  # type: ignore[override]
        self,
        system_prompt: str,
        history: list[ChatTurn],
        user_message: str,
    ) -> AsyncIterator[str]:
        messages = [{"role": "system", "content": system_prompt}]
        messages.extend({"role": t["role"], "content": t["content"]} for t in history)
        messages.append({"role": "user", "content": user_message})
        resp = await self._openai.chat.completions.create(
            model=self._model, messages=messages, stream=True
        )
        async for chunk in resp:
            delta = chunk.choices[0].delta.content
            if delta:
                yield delta
