import json
import pytest
from concierge.llm.openai_client import OpenAILLMClient
from concierge.llm.client import LLMError


class _StubMessage:
    def __init__(self, content): self.message = type("M", (), {"content": content})


class _StubResp:
    def __init__(self, content): self.choices = [_StubMessage(content)]


class _StubCompletions:
    def __init__(self, content=None, exc=None): self._content, self._exc = content, exc
    def create(self, **kwargs):
        if self._exc: raise self._exc
        return _StubResp(self._content)


class _StubClient:
    def __init__(self, content=None, exc=None):
        self.chat = type("C", (), {"completions": _StubCompletions(content, exc)})


def test_complete_json_parses_content():
    c = OpenAILLMClient(api_key="x")
    c._client = _StubClient(content=json.dumps({"a": 1}))
    assert c.complete_json("sys", "user") == {"a": 1}


def test_complete_json_wraps_errors():
    c = OpenAILLMClient(api_key="x")
    c._client = _StubClient(exc=RuntimeError("network"))
    with pytest.raises(LLMError):
        c.complete_json("sys", "user")


def test_complete_json_wraps_bad_json():
    c = OpenAILLMClient(api_key="x")
    c._client = _StubClient(content="not json")
    with pytest.raises(LLMError):
        c.complete_json("sys", "user")
