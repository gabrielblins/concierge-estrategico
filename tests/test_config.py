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
