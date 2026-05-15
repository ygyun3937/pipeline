from __future__ import annotations

import os
from collections.abc import AsyncIterator

from claude_agent_sdk import ClaudeAgentOptions, query

from src._agent_lock import AGENT_ENV_LOCK as _AGENT_ENV_LOCK
from src.llm.base import ChatTurn
from src.logger import get_logger

logger = get_logger(__name__)


class ClaudeClient:
    """claude_agent_sdk를 사용하는 LLM 클라이언트 (인터넷 연결 환경)."""

    @property
    def model_name(self) -> str:
        return "claude-agent-sdk"

    async def complete(self, system_prompt: str, user_message: str) -> str:
        async with _AGENT_ENV_LOCK:
            claudecode_env = os.environ.pop("CLAUDECODE", None)
            try:
                answer = ""
                async for message in query(
                    prompt=user_message,
                    options=ClaudeAgentOptions(
                        allowed_tools=[],
                        system_prompt=system_prompt,
                    ),
                ):
                    if hasattr(message, "result") and message.result:
                        answer = message.result

                if not answer:
                    raise RuntimeError("Claude Agent SDK가 응답을 반환하지 않았습니다.")
                return answer
            finally:
                if claudecode_env is not None:
                    os.environ["CLAUDECODE"] = claudecode_env

    async def stream(self, system_prompt: str, user_message: str) -> AsyncIterator[str]:  # type: ignore[override]
        # claude_agent_sdk는 진짜 스트리밍을 지원하지 않으므로
        # complete() 결과를 단일 청크로 yield한다.
        result = await self.complete(system_prompt, user_message)
        yield result

    async def complete_with_history(
        self,
        system_prompt: str,
        history: list[ChatTurn],
        user_message: str,
    ) -> str:
        # SDK가 멀티턴을 지원하지 않으므로 이력을 대화 형식으로 직렬화한다.
        prefix = "\n".join(
            f"[{'사용자' if t['role'] == 'user' else 'AI'}]: {t['content']}"
            for t in history
        )
        combined = f"{prefix}\n[사용자]: {user_message}" if prefix else user_message
        return await self.complete(system_prompt, combined)

    async def stream_with_history(  # type: ignore[override]
        self,
        system_prompt: str,
        history: list[ChatTurn],
        user_message: str,
    ) -> AsyncIterator[str]:
        result = await self.complete_with_history(system_prompt, history, user_message)
        yield result
