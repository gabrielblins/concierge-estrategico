import pytest
from pydantic import BaseModel
from concierge.llm.client import LLMClient, FakeLLMClient, LLMError, call_validated


def test_fake_returns_queued_responses_in_order():
    fake = FakeLLMClient(responses=[{"a": 1}, {"b": 2}])
    assert fake.complete_json("sys", "u1") == {"a": 1}
    assert fake.complete_json("sys", "u2") == {"b": 2}
    assert fake.calls == [("sys", "u1"), ("sys", "u2")]


def test_fake_raises_configured_error():
    fake = FakeLLMClient(error=LLMError("boom"))
    with pytest.raises(LLMError):
        fake.complete_json("sys", "u")


class Sample(BaseModel):
    x: int


def test_call_validated_returns_model_on_valid():
    fake = FakeLLMClient(responses=[{"x": 5}])
    out = call_validated(fake, "sys", "u", Sample)
    assert out == Sample(x=5)


def test_call_validated_retries_once_then_returns_none():
    # first response invalid, second also invalid -> None after one retry
    fake = FakeLLMClient(responses=[{"x": "bad"}, {"x": "bad"}])
    out = call_validated(fake, "sys", "u", Sample)
    assert out is None
    assert len(fake.calls) == 2


def test_call_validated_recovers_on_retry():
    fake = FakeLLMClient(responses=[{"x": "bad"}, {"x": 9}])
    out = call_validated(fake, "sys", "u", Sample)
    assert out == Sample(x=9)


def test_call_validated_handles_llm_error():
    fake = FakeLLMClient(error=LLMError("down"))
    assert call_validated(fake, "sys", "u", Sample) is None
