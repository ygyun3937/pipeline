from __future__ import annotations

from openai import AsyncOpenAI

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
