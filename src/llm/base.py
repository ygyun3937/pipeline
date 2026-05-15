from collections.abc import AsyncIterator
from typing import Protocol, TypedDict, runtime_checkable


class ChatTurn(TypedDict):
    """대화 이력 단위 (role: 'user' | 'assistant')."""
    role: str
    content: str


@runtime_checkable
class LLMClient(Protocol):
    """LLM 백엔드 공통 인터페이스."""

    @property
    def model_name(self) -> str: ...

    async def complete(self, system_prompt: str, user_message: str) -> str:
        """단일 턴: 시스템 프롬프트 + 사용자 메시지 → 응답 텍스트."""
        ...

    def stream(self, system_prompt: str, user_message: str) -> AsyncIterator[str]:
        """단일 턴 스트리밍."""
        ...

    async def complete_with_history(
        self,
        system_prompt: str,
        history: list[ChatTurn],
        user_message: str,
    ) -> str:
        """멀티턴: 이전 대화 이력 포함하여 응답 텍스트를 반환한다."""
        ...

    def stream_with_history(
        self,
        system_prompt: str,
        history: list[ChatTurn],
        user_message: str,
    ) -> AsyncIterator[str]:
        """멀티턴 스트리밍."""
        ...
