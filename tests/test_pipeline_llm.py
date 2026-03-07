from unittest.mock import MagicMock, patch
from src.config import Settings
from src.pipeline import IssuePipeline
from src.llm import OllamaClient, ClaudeClient


def _make_settings(**kwargs):
    """테스트용 최소 Settings 생성."""
    return Settings(**kwargs)


def test_claude_backend_by_default(tmp_path):
    """기본값(llm_backend=claude)이면 ClaudeClient가 선택된다."""
    with patch("src.pipeline.DocumentLoader"), \
         patch("src.pipeline.IssueEmbedder"), \
         patch("src.pipeline.IssueRetriever"):
        pipeline = IssuePipeline.from_settings(Settings())
    assert isinstance(pipeline._llm_client, ClaudeClient)


def test_ollama_backend_when_configured(monkeypatch, tmp_path):
    """LLM_BACKEND=ollama이면 OllamaClient가 선택된다."""
    monkeypatch.setenv("LLM_BACKEND", "ollama")
    with patch("src.pipeline.DocumentLoader"), \
         patch("src.pipeline.IssueEmbedder"), \
         patch("src.pipeline.IssueRetriever"):
        pipeline = IssuePipeline.from_settings(Settings())
    assert isinstance(pipeline._llm_client, OllamaClient)
