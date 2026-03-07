from __future__ import annotations

import os

from claude_agent_sdk import ClaudeAgentOptions, query

from src._agent_lock import AGENT_ENV_LOCK as _AGENT_ENV_LOCK
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
                return answer
            finally:
                if claudecode_env is not None:
                    os.environ["CLAUDECODE"] = claudecode_env
