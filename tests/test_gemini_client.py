import json
import pytest
from concierge.llm.gemini_client import GeminiLLMClient
from concierge.llm.client import LLMError


class _StubResp:
    def __init__(self, text):
        self.text = text


class _StubModels:
    def __init__(self, text=None, exc=None):
        self._text, self._exc = text, exc
        self.calls = []

    def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        if self._exc:
            raise self._exc
        return _StubResp(self._text)


class _StubClient:
    def __init__(self, text=None, exc=None):
        self.models = _StubModels(text=text, exc=exc)


def test_complete_json_parses_text():
    c = GeminiLLMClient(api_key="x")
    c._client = _StubClient(text=json.dumps({"a": 1}))
    assert c.complete_json("sys", "user") == {"a": 1}


def test_complete_json_passes_system_and_user_and_json_mime():
    c = GeminiLLMClient(api_key="x", model="gemini-3.5-flash")
    c._client = _StubClient(text=json.dumps({"ok": True}))
    c.complete_json("be helpful", "the user message")
    call = c._client.models.calls[0]
    assert call["model"] == "gemini-3.5-flash"
    assert call["contents"] == "the user message"
    # system instruction + JSON mime are on the config object
    cfg = call["config"]
    assert cfg.system_instruction == "be helpful"
    assert cfg.response_mime_type == "application/json"


def test_complete_json_wraps_transport_error():
    c = GeminiLLMClient(api_key="x")
    c._client = _StubClient(exc=RuntimeError("network"))
    with pytest.raises(LLMError):
        c.complete_json("sys", "user")


def test_complete_json_wraps_bad_json():
    c = GeminiLLMClient(api_key="x")
    c._client = _StubClient(text="not json")
    with pytest.raises(LLMError):
        c.complete_json("sys", "user")
