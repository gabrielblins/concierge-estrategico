import pytest
from concierge.llm.client import LLMClient, FakeLLMClient, LLMError


def test_fake_returns_queued_responses_in_order():
    fake = FakeLLMClient(responses=[{"a": 1}, {"b": 2}])
    assert fake.complete_json("sys", "u1") == {"a": 1}
    assert fake.complete_json("sys", "u2") == {"b": 2}
    assert fake.calls == [("sys", "u1"), ("sys", "u2")]


def test_fake_raises_configured_error():
    fake = FakeLLMClient(error=LLMError("boom"))
    with pytest.raises(LLMError):
        fake.complete_json("sys", "u")
