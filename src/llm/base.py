from collections.abc import AsyncIterator
from typing import Protocol, runtime_checkable


@runtime_checkable
class LLMClient(Protocol):
    """LLM 백엔드 공통 인터페이스."""

    # NOTE: @runtime_checkable only checks attribute/method *presence* at runtime,
    # not whether `complete` is actually a coroutine function. A sync implementation
    # passes isinstance() checks silently. The only valid backends are ClaudeClient
    # and OllamaClient defined in this package.

    @property
    def model_name(self) -> str: ...

    async def complete(self, system_prompt: str, user_message: str) -> str:
        """시스템 프롬프트와 사용자 메시지를 받아 LLM 응답 텍스트를 반환한다."""
        ...

    def stream(self, system_prompt: str, user_message: str) -> AsyncIterator[str]:
        """응답 텍스트를 청크 단위로 스트리밍한다."""
        ...
