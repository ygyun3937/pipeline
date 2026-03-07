"""src/config.py의 Settings 클래스에 대한 단위 테스트."""

from src.config import Settings


def test_default_llm_backend_is_claude():
    s = Settings()
    assert s.llm_backend == "claude"


def test_ollama_settings_defaults():
    s = Settings()
    assert s.ollama_base_url == "http://localhost:11434"
    assert s.ollama_model == "qwen2.5:7b"


def test_llm_backend_from_env(monkeypatch):
    monkeypatch.setenv("LLM_BACKEND", "ollama")
    s = Settings()
    assert s.llm_backend == "ollama"
