from unittest.mock import patch
from src.config import Settings
from src.pipeline import IssuePipeline
from src.llm import OllamaClient, ClaudeClient


def test_claude_backend_by_default():
    """기본값(llm_backend=claude)이면 ClaudeClient가 선택된다."""
    with patch("src.pipeline.DocumentLoader"), \
         patch("src.pipeline.IssueEmbedder"), \
         patch("src.pipeline.IssueRetriever"):
        pipeline = IssuePipeline.from_settings(Settings())
    assert isinstance(pipeline._llm_client, ClaudeClient)


def test_ollama_backend_when_configured(monkeypatch):
    """LLM_BACKEND=ollama이면 OllamaClient가 선택된다."""
    monkeypatch.setenv("LLM_BACKEND", "ollama")
    with patch("src.pipeline.DocumentLoader"), \
         patch("src.pipeline.IssueEmbedder"), \
         patch("src.pipeline.IssueRetriever"):
        pipeline = IssuePipeline.from_settings(Settings())
    assert isinstance(pipeline._llm_client, OllamaClient)
