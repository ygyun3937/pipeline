from typing import Protocol, runtime_checkable


@runtime_checkable
class LLMClient(Protocol):
    """LLM 백엔드 공통 인터페이스."""

    @property
    def model_name(self) -> str: ...

    async def complete(self, system_prompt: str, user_message: str) -> str:
        """시스템 프롬프트와 사용자 메시지를 받아 LLM 응답 텍스트를 반환한다."""
        ...
