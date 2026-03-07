import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from src.llm.claude_client import ClaudeClient
from src.llm.ollama_client import OllamaClient


class TestClaudeClient:
    def test_model_name(self):
        client = ClaudeClient()
        assert client.model_name == "claude-agent-sdk"

    @pytest.mark.asyncio
    async def test_complete_returns_string(self):
        client = ClaudeClient()
        mock_msg = MagicMock()
        mock_msg.result = "테스트 응답"

        async def fake_query(*args, **kwargs):
            yield mock_msg

        with patch("src.llm.claude_client.query", side_effect=fake_query):
            result = await client.complete("시스템 프롬프트", "사용자 메시지")
        assert result == "테스트 응답"

    @pytest.mark.asyncio
    async def test_complete_raises_on_empty_result(self):
        client = ClaudeClient()
        mock_msg = MagicMock()
        mock_msg.result = None  # no result

        async def fake_query(*args, **kwargs):
            yield mock_msg

        with patch("src.llm.claude_client.query", side_effect=fake_query):
            with pytest.raises(RuntimeError, match="응답을 반환하지 않았습니다"):
                await client.complete("sys", "user")


class TestOllamaClient:
    def test_model_name(self):
        client = OllamaClient(base_url="http://localhost:11434", model="qwen2.5:7b")
        assert client.model_name == "qwen2.5:7b"

    @pytest.mark.asyncio
    async def test_complete_returns_string(self):
        client = OllamaClient(base_url="http://localhost:11434", model="qwen2.5:7b")

        mock_choice = MagicMock()
        mock_choice.message.content = "Ollama 응답"
        mock_resp = MagicMock()
        mock_resp.choices = [mock_choice]

        client._openai.chat.completions.create = AsyncMock(return_value=mock_resp)

        result = await client.complete("시스템", "메시지")
        assert result == "Ollama 응답"
