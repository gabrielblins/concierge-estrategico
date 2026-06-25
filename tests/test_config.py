import os
from concierge.config import Settings


def test_settings_from_env_reads_values_and_defaults(monkeypatch):
    monkeypatch.setenv("TELEGRAM_TOKEN", "tok")
    monkeypatch.setenv("OPENAI_API_KEY", "key")
    monkeypatch.delenv("BATCH_SIZE", raising=False)
    s = Settings.from_env()
    assert s.telegram_token == "tok"
    assert s.openai_api_key == "key"
    assert s.batch_size == 15
    assert s.confidence_threshold == 0.75


def test_settings_from_env_reads_llm_provider_fields(monkeypatch):
    monkeypatch.setenv("TELEGRAM_TOKEN", "tok")
    monkeypatch.setenv("OPENAI_API_KEY", "okey")
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "gkey")
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    s = Settings.from_env()
    assert s.llm_provider == "gemini"
    assert s.gemini_api_key == "gkey"
    assert s.gemini_model == "gemini-3.5-flash"     # default
    assert s.openai_model == "gpt-4o-mini"          # default


def test_settings_llm_provider_defaults_to_openai(monkeypatch):
    monkeypatch.setenv("TELEGRAM_TOKEN", "tok")
    monkeypatch.setenv("OPENAI_API_KEY", "okey")
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    s = Settings.from_env()
    assert s.llm_provider == "openai"
