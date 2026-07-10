from pydantic import BaseModel

from google.adk.agents import LlmAgent

from concierge.agents.executor import AgentExecutor
from tests.test_agents_spike import FakeAdkModel


class Sample(BaseModel):
    x: int


def _agent(responses):
    return LlmAgent(name="unit", model=FakeAdkModel(responses=list(responses)),
                    instruction="return json")


def test_run_text_returns_final_text():
    ex = AgentExecutor()
    assert ex.run_text(_agent(["hello"]), "oi") == "hello"


def test_run_validated_happy_path():
    ex = AgentExecutor()
    out = ex.run_validated(_agent(['{"x": 5}']), "oi", Sample)
    assert out == Sample(x=5)


def test_run_validated_retries_once_then_none():
    ex = AgentExecutor()
    assert ex.run_validated(_agent(["not json", "still bad"]), "oi", Sample) is None


def test_run_validated_recovers_on_retry():
    ex = AgentExecutor()
    out = ex.run_validated(_agent(["nope", '{"x": 9}']), "oi", Sample)
    assert out == Sample(x=9)


def test_run_text_survives_agent_exception():
    class Boom(FakeAdkModel):
        async def generate_content_async(self, llm_request, stream=False):
            raise RuntimeError("kaput")
            yield  # pragma: no cover

    ex = AgentExecutor()
    agent = LlmAgent(name="boom", model=Boom(), instruction="x")
    assert ex.run_text(agent, "oi") is None


def test_works_when_called_from_inside_an_event_loop():
    import asyncio

    ex = AgentExecutor()

    async def inside():
        return ex.run_text(_agent(["from-loop"]), "oi")

    assert asyncio.run(inside()) == "from-loop"
