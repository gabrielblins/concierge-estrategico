"""Spike: proves the google-adk 2.3.0 surface this migration relies on.

If any import/call here needs adjustment, FIX IT HERE and record the
correction in the task report — later tasks copy these patterns.
"""
import asyncio

import pytest
from pydantic import BaseModel

from google.adk.agents import LlmAgent
from google.adk.agents.base_agent import BaseAgent
from google.adk.events.event import Event
from google.adk.events.event_actions import EventActions
from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_response import LlmResponse
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from concierge.agents.model_factory import agent_model, configure_env
from concierge.config import Settings


class FakeAdkModel(BaseLlm):
    """Queue-backed fake model consumed by the REAL Runner."""

    model: str = "fake-model"
    responses: list = []

    async def generate_content_async(self, llm_request, stream=False):
        text = self.responses.pop(0) if self.responses else "{}"
        yield LlmResponse(
            content=types.Content(role="model", parts=[types.Part(text=text)])
        )


def _run_agent(agent, user_text):
    async def go():
        session_service = InMemorySessionService()
        runner = Runner(app_name="spike", agent=agent,
                        session_service=session_service)
        session = await session_service.create_session(
            app_name="spike", user_id="u")
        final = ""
        async for event in runner.run_async(
            user_id="u", session_id=session.id,
            new_message=types.Content(role="user",
                                      parts=[types.Part(text=user_text)]),
        ):
            if event.content and event.content.parts:
                for p in event.content.parts:
                    if p.text:
                        final = p.text
        return final
    return asyncio.run(go())


def test_llm_agent_runs_with_fake_model():
    agent = LlmAgent(name="probe", model=FakeAdkModel(responses=['{"ok": true}']),
                     instruction="Return JSON.")
    out = _run_agent(agent, "ping")
    assert '"ok"' in out


def test_model_factory_gemini_and_openai():
    s_g = Settings(telegram_token="t", openai_api_key="", gemini_api_key="g",
                   llm_provider="gemini", gemini_model="gemini-3.5-flash")
    assert agent_model(s_g) == "gemini-3.5-flash"
    s_o = Settings(telegram_token="t", openai_api_key="ok",
                   llm_provider="openai", openai_model="gpt-5.4-mini")
    m = agent_model(s_o)
    from google.adk.models.lite_llm import LiteLlm
    assert isinstance(m, LiteLlm)
    assert m.model == "openai/gpt-5.4-mini"


def test_configure_env_maps_gemini_key(monkeypatch):
    import os
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    s = Settings(telegram_token="t", openai_api_key="", gemini_api_key="gkey")
    configure_env(s)
    assert os.environ["GOOGLE_API_KEY"] == "gkey"


class _StateProbe(BaseAgent):
    async def _run_async_impl(self, ctx):
        # NOTE (API correction): mutating `ctx.session.state` in place is NOT
        # persisted by the session service. The Runner commits state only via
        # `session_service.append_event(session, event)`, which merges
        # `event.actions.state_delta` into storage (see
        # InMemorySessionService.append_event). A plain in-memory mutation on
        # ctx.session.state is invisible to a later `get_session` call because
        # that method returns a session built from storage, not this object.
        # So: yield an Event carrying the delta instead of mutating state.
        probe_value = ctx.session.state.get("seed", 0) + 1
        yield Event(
            author=self.name,
            invocation_id=ctx.invocation_id,
            actions=EventActions(state_delta={"probe": probe_value}),
        )
        for sub in self.sub_agents:
            async for ev in sub.run_async(ctx):
                yield ev


def test_custom_agent_with_sub_agents_and_state():
    child = LlmAgent(name="child", model=FakeAdkModel(responses=["pong"]),
                     instruction="say pong")
    root = _StateProbe(name="root", sub_agents=[child])

    async def go():
        session_service = InMemorySessionService()
        runner = Runner(app_name="spike2", agent=root,
                        session_service=session_service)
        session = await session_service.create_session(
            app_name="spike2", user_id="u", state={"seed": 41})
        texts = []
        async for event in runner.run_async(
            user_id="u", session_id=session.id,
            new_message=types.Content(role="user",
                                      parts=[types.Part(text="hi")]),
        ):
            if event.content and event.content.parts:
                texts += [p.text for p in event.content.parts if p.text]
        session = await session_service.get_session(
            app_name="spike2", user_id="u", session_id=session.id)
        return texts, session.state
    texts, state = asyncio.run(go())
    assert "pong" in "".join(texts)
    assert state["probe"] == 42
