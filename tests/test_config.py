"""src/config.py의 Settings 클래스에 대한 단위 테스트."""

from src.config import Settings


def test_default_llm_backend_is_claude(monkeypatch):
    monkeypatch.delenv("LLM_BACKEND", raising=False)
    s = Settings(_env_file=None)
    assert s.llm_backend == "claude"


def test_ollama_settings_defaults():
    s = Settings()
    assert s.ollama_base_url == "http://localhost:11434"
    assert s.ollama_model == "qwen2.5:7b"


def test_llm_backend_from_env(monkeypatch):
    monkeypatch.setenv("LLM_BACKEND", "ollama")
    s = Settings()
    assert s.llm_backend == "ollama"


def test_default_postgres_url(monkeypatch):
    monkeypatch.delenv("POSTGRES_URL", raising=False)
    s = Settings(_env_file=None)
    assert "pipeline" in s.postgres_url
    assert "5435" in s.postgres_url


def test_postgres_async_url_prefix():
    s = Settings()
    assert s.postgres_async_url.startswith("postgresql+asyncpg://")


def test_postgres_sync_url_prefix():
    s = Settings()
    assert s.postgres_sync_url.startswith("postgresql+psycopg://")


def test_postgres_url_from_env(monkeypatch):
    monkeypatch.setenv("POSTGRES_URL", "postgresql://user:pass@host:5432/db")
    s = Settings()
    assert s.postgres_url == "postgresql://user:pass@host:5432/db"
    assert s.postgres_async_url == "postgresql+asyncpg://user:pass@host:5432/db"
    assert s.postgres_sync_url == "postgresql+psycopg://user:pass@host:5432/db"
