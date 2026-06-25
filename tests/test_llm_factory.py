import pytest
from concierge.config import Settings
from concierge.llm.factory import build_llm
from concierge.llm.client import LLMError
from concierge.llm.openai_client import OpenAILLMClient
from concierge.llm.gemini_client import GeminiLLMClient


def _settings(**kw):
    base = dict(telegram_token="t", openai_api_key="", gemini_api_key="")
    base.update(kw)
    return Settings(**base)


def test_build_openai_client():
    s = _settings(llm_provider="openai", openai_api_key="okey", openai_model="gpt-4o-mini")
    client = build_llm(s)
    assert isinstance(client, OpenAILLMClient)
    assert client.model == "gpt-4o-mini"


def test_build_gemini_client():
    s = _settings(llm_provider="gemini", gemini_api_key="gkey", gemini_model="gemini-3.5-flash")
    client = build_llm(s)
    assert isinstance(client, GeminiLLMClient)
    assert client.model == "gemini-3.5-flash"


def test_provider_is_case_insensitive_and_trimmed():
    s = _settings(llm_provider="  GEMINI  ", gemini_api_key="gkey")
    assert isinstance(build_llm(s), GeminiLLMClient)


def test_missing_openai_key_raises():
    s = _settings(llm_provider="openai", openai_api_key="")
    with pytest.raises(LLMError):
        build_llm(s)


def test_missing_gemini_key_raises():
    s = _settings(llm_provider="gemini", gemini_api_key="")
    with pytest.raises(LLMError):
        build_llm(s)


def test_unknown_provider_raises():
    s = _settings(llm_provider="anthropic")
    with pytest.raises(LLMError):
        build_llm(s)
