# Google ADK Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Google ADK becomes the main agent framework: all 8 LLM units become ADK `LlmAgent`s run through the real `Runner`, the non-mention message path is orchestrated by a deterministic custom ADK agent, and the old `llm/` layer is removed.

**Architecture:** New `agents/` package: `model_factory` (gemini native string | `LiteLlm("openai/...")`), `definitions` (8 LlmAgents whose `instruction`s are today's SYSTEM prompts), `executor` (`AgentExecutor` — background-thread event loop bridging our sync contracts into `Runner.run_async`; `run_validated` keeps the retry-once-then-None Pydantic semantics), `funnel` (`MessageFunnelAgent(BaseAgent)` — deterministic gates + guardian/participant sub-agents). Existing unit modules become thin facades with identical public contracts; tests swap `fake_llm` for `fake_executor`.

**Tech Stack:** google-adk 2.3.0, litellm 1.83.7, Python 3.14, pydantic, existing pytest suite (133 tests).

## Global Constraints

- Pins: `google-adk==2.3.0`, `litellm==1.83.7` added to requirements.txt (installed in the venv already; opentelemetry resolver warning is accepted/non-fatal).
- Invariants preserved exactly: retry-1x-then-None on invalid output (never raise, never persist garbage); trivial message = zero agent runs (gates before any agent); one voice per message with guardian priority; silence on failure; all public unit contracts unchanged (`Extractor.extract`, `Guardian.check/looks_strategic`, `CanvasUpdater.update`, `Reconciler.reconcile`, `Participant.consider/respond`, `Stylist.restyle`, `materials.classify`, all Orchestrator methods).
- Style/voice moves from SYSTEM suffix to a USER-prompt suffix (`Write in this voice: {style}` block) — judgment neutrality unchanged.
- `bot.py`, `storage.py`, `knowledge.py`, `webapp/`, `models.py`, `config.py` untouched (except `main.py` wiring).
- `llm/` package and its tests are DELETED at the end (Task 7) — not before, so the suite stays green between tasks.
- All business tests run without network: `FakeAdkModel(BaseLlm)` for executor tests (real Runner, canned responses); `fake_executor` fixture for facades.
- Shared venv `. .venv/bin/activate` (Python 3.14.3); suite currently 133 passed. Branch: `feat/adk-migration`.
- **Task 1 is an API-verification spike**: if google-adk 2.3.0's real API differs from this plan's assumptions, the implementer records the corrections in its report; the controller amends later task briefs accordingly.

---

## File Structure

```
src/concierge/agents/
  __init__.py        # empty
  model_factory.py   # agent_model(settings), configure_env(settings)
  definitions.py     # build_agents(model) -> dict[str, LlmAgent]; INSTRUCTIONS dict
  executor.py        # AgentExecutor (bg loop thread, run_text, run_validated)
  funnel.py          # MessageFunnelAgent(BaseAgent)
src/concierge/       # facades: extractor/updater/reconciler/guardian/
                     #   participant/stylist/materials (classify) delegate to executor
tests/
  test_agents_spike.py      # Task 1 (API proof; kept as regression)
  test_agent_executor.py    # Task 2
  test_agent_definitions.py # Task 3
  test_funnel.py            # Task 6
  conftest.py               # +fake_executor (Task 4); fake_llm removed in Task 7
  (existing unit test files migrated in Tasks 4–5; test_llm_*.py deleted in Task 7)
```

---

### Task 1: Spike — prove the ADK 2.3.0 API surface

**Files:**
- Create: `src/concierge/agents/__init__.py` (empty), `src/concierge/agents/model_factory.py`
- Create: `tests/test_agents_spike.py`
- Modify: `requirements.txt` (append `google-adk==2.3.0`, `litellm==1.83.7`)
- Modify: `tests/test_config.py` — no change expected; run only.

**Interfaces:**
- Produces: `agent_model(settings)` → `str` (gemini) | `LiteLlm` (openai); `configure_env(settings)` → sets `os.environ["GOOGLE_API_KEY"]` from `settings.gemini_api_key` when non-empty (OPENAI_API_KEY already comes from the environment). Also produces the **verified knowledge** later tasks rely on: how to build a `FakeAdkModel(BaseLlm)`, run an `LlmAgent` through `Runner` with `InMemorySessionService`, read the final response text, and how a custom `BaseAgent` subclass with `sub_agents` + `ctx.session.state` behaves.

- [ ] **Step 1: Write the spike test** — `tests/test_agents_spike.py`. This test IS the API proof; adapt internals if 2.3.0 differs, but the ASSERTED behaviors must hold:

```python
"""Spike: proves the google-adk 2.3.0 surface this migration relies on.

If any import/call here needs adjustment, FIX IT HERE and record the
correction in the task report — later tasks copy these patterns.
"""
import asyncio

import pytest
from pydantic import BaseModel

from google.adk.agents import LlmAgent
from google.adk.agents.base_agent import BaseAgent
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
        ctx.session.state["probe"] = ctx.session.state.get("seed", 0) + 1
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
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_agents_spike.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'concierge.agents'` (and possibly import corrections needed — fix imports per installed package, record in report).

- [ ] **Step 3: Implement `src/concierge/agents/model_factory.py`**

```python
import os


def configure_env(settings) -> None:
    """Export the env vars ADK/litellm read for the configured provider."""
    if settings.gemini_api_key:
        os.environ.setdefault("GOOGLE_API_KEY", settings.gemini_api_key)


def agent_model(settings):
    """Return the ADK model spec for the configured provider."""
    provider = settings.llm_provider.strip().lower()
    if provider == "gemini":
        return settings.gemini_model
    from google.adk.models.lite_llm import LiteLlm

    return LiteLlm(model=f"openai/{settings.openai_model}")
```

- [ ] **Step 4: Run to verify pass — adapting the spike as needed**

Run: `pytest tests/test_agents_spike.py -v`
Expected: PASS (4 passed). If any ADK import path/signature differs in 2.3.0 (e.g. `BaseLlm` location, `LlmResponse` construction, `Runner` kwargs, `create_session` signature, `sub_agents` wiring), ADJUST THE SPIKE and record every correction in the report under a heading "API corrections".

- [ ] **Step 5: Append pins to `requirements.txt`**

```
google-adk==2.3.0
litellm==1.83.7
```

- [ ] **Step 6: Full suite** — `pytest -q` (expect 137 passed: 133 + 4).

- [ ] **Step 7: Commit**

```bash
git add src/concierge/agents/__init__.py src/concierge/agents/model_factory.py tests/test_agents_spike.py requirements.txt
git commit -m "feat: adk spike — model factory and verified runner/agent patterns"
```

---

### Task 2: AgentExecutor

**Files:**
- Create: `src/concierge/agents/executor.py`
- Create: `tests/test_agent_executor.py`

**Interfaces:**
- Consumes: the spike's verified patterns (`FakeAdkModel`, Runner usage) — copy them from `tests/test_agents_spike.py`, including any Task-1 corrections.
- Produces: `AgentExecutor()` with:
  - a dedicated background event loop thread (created lazily, daemon) and `_submit(coro)` running `asyncio.run_coroutine_threadsafe(coro, self._loop).result()`;
  - `run_text(agent, user_text) -> str | None` — fresh session per call (`app_name="concierge"`, `user_id="bot"`), final text per the spike's event-reading pattern; ANY exception → `None`;
  - `run_validated(agent, user_text, schema) -> BaseModel | None` — up to 2 attempts: `run_text` → `json.loads` → `schema.model_validate`; failure of any step continues to the retry; both failed → `None`. Never raises.

- [ ] **Step 1: Write the failing test** — `tests/test_agent_executor.py`:

```python
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
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_agent_executor.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'concierge.agents.executor'`

- [ ] **Step 3: Implement `src/concierge/agents/executor.py`**

```python
import asyncio
import json
import threading
import uuid

from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types
from pydantic import ValidationError


class AgentExecutor:
    """Runs ADK agents from synchronous code.

    Owns a dedicated event loop in a daemon thread so callers inside an
    already-running loop (the telegram bot) can block on agent results.
    """

    def __init__(self):
        self._loop = None
        self._lock = threading.Lock()

    def _ensure_loop(self):
        with self._lock:
            if self._loop is None:
                self._loop = asyncio.new_event_loop()
                thread = threading.Thread(
                    target=self._loop.run_forever, daemon=True,
                    name="adk-executor",
                )
                thread.start()
        return self._loop

    def _submit(self, coro):
        loop = self._ensure_loop()
        return asyncio.run_coroutine_threadsafe(coro, loop).result()

    async def _run(self, agent, user_text):
        session_service = InMemorySessionService()
        runner = Runner(
            app_name="concierge", agent=agent, session_service=session_service
        )
        session = await session_service.create_session(
            app_name="concierge", user_id="bot",
            session_id=uuid.uuid4().hex,
        )
        final = ""
        async for event in runner.run_async(
            user_id="bot", session_id=session.id,
            new_message=types.Content(
                role="user", parts=[types.Part(text=user_text)]
            ),
        ):
            if event.content and event.content.parts:
                for part in event.content.parts:
                    if part.text:
                        final = part.text
        return final

    def run_text(self, agent, user_text):
        try:
            return self._submit(self._run(agent, user_text))
        except Exception:
            return None

    def run_validated(self, agent, user_text, schema):
        for _ in range(2):
            text = self.run_text(agent, user_text)
            if text is None:
                continue
            try:
                return schema.model_validate(json.loads(text))
            except (ValueError, ValidationError):
                continue
        return None
```

(If Task 1 recorded corrections to session/runner calls, apply the same here.)

- [ ] **Step 4: Run to verify pass** — `pytest tests/test_agent_executor.py -v` (6 passed); `pytest -q` (expect 143).

- [ ] **Step 5: Commit**

```bash
git add src/concierge/agents/executor.py tests/test_agent_executor.py
git commit -m "feat: AgentExecutor bridges sync contracts onto the adk runner"
```

---

### Task 3: Agent definitions

**Files:**
- Create: `src/concierge/agents/definitions.py`
- Create: `tests/test_agent_definitions.py`

**Interfaces:**
- Consumes: `agent_model` output types (str | LiteLlm).
- Produces: `AGENT_NAMES = ["extractor", "reconciler", "canvas_updater", "guardian", "participant_consider", "participant_respond", "stylist", "material_classifier"]`; `INSTRUCTIONS: dict[str, str]` — the SYSTEM prompts copied VERBATIM from the current modules (`extractor.SYSTEM`, `reconciler.SYSTEM`, `updater.SYSTEM`, `guardian.SYSTEM`, `participant.CONSIDER_SYSTEM`, `participant.RESPOND_SYSTEM`, `stylist.SYSTEM`, `materials.CLASSIFY_SYSTEM`); `build_agents(model) -> dict[str, LlmAgent]` — one LlmAgent per name with that instruction and the shared model.

- [ ] **Step 1: Write the failing test** — `tests/test_agent_definitions.py`:

```python
from concierge.agents.definitions import AGENT_NAMES, INSTRUCTIONS, build_agents
from tests.test_agents_spike import FakeAdkModel


def test_all_eight_agents_defined():
    assert AGENT_NAMES == [
        "extractor", "reconciler", "canvas_updater", "guardian",
        "participant_consider", "participant_respond", "stylist",
        "material_classifier",
    ]
    assert set(INSTRUCTIONS) == set(AGENT_NAMES)


def test_instructions_carry_the_original_contracts():
    assert "decision|hypothesis|premise|risk|task|learning" in INSTRUCTIONS["extractor"]
    assert "contradicts" in INSTRUCTIONS["guardian"]
    assert "should_contribute" in INSTRUCTIONS["participant_consider"]
    assert "validated|discarded" in INSTRUCTIONS["reconciler"]
    assert "block_name" in INSTRUCTIONS["canvas_updater"]
    assert "canvas_guide|validation_guide" in INSTRUCTIONS["material_classifier"]


def test_build_agents_wires_model_and_instruction():
    model = FakeAdkModel(responses=[])
    agents = build_agents(model)
    assert set(agents) == set(AGENT_NAMES)
    assert agents["guardian"].instruction == INSTRUCTIONS["guardian"]
    assert agents["guardian"].model is model
```

- [ ] **Step 2: Run to verify failure** — `pytest tests/test_agent_definitions.py -v` → `ModuleNotFoundError`.

- [ ] **Step 3: Implement `src/concierge/agents/definitions.py`** — import the SYSTEM constants from the existing modules (they still exist until Task 7 removes none of them — the facades keep their prompt constants THIS task simply re-exports):

```python
from google.adk.agents import LlmAgent

from concierge.extractor import SYSTEM as EXTRACTOR_SYSTEM
from concierge.guardian import SYSTEM as GUARDIAN_SYSTEM
from concierge.materials import CLASSIFY_SYSTEM
from concierge.participant import CONSIDER_SYSTEM, RESPOND_SYSTEM
from concierge.reconciler import SYSTEM as RECONCILER_SYSTEM
from concierge.stylist import SYSTEM as STYLIST_SYSTEM
from concierge.updater import SYSTEM as UPDATER_SYSTEM

AGENT_NAMES = [
    "extractor", "reconciler", "canvas_updater", "guardian",
    "participant_consider", "participant_respond", "stylist",
    "material_classifier",
]

INSTRUCTIONS = {
    "extractor": EXTRACTOR_SYSTEM,
    "reconciler": RECONCILER_SYSTEM,
    "canvas_updater": UPDATER_SYSTEM,
    "guardian": GUARDIAN_SYSTEM,
    "participant_consider": CONSIDER_SYSTEM,
    "participant_respond": RESPOND_SYSTEM,
    "stylist": STYLIST_SYSTEM,
    "material_classifier": CLASSIFY_SYSTEM,
}


def build_agents(model):
    return {
        name: LlmAgent(name=name, model=model, instruction=INSTRUCTIONS[name])
        for name in AGENT_NAMES
    }
```

- [ ] **Step 4: Run to verify pass** — `pytest tests/test_agent_definitions.py -v` (3 passed); `pytest -q` (expect 146).

- [ ] **Step 5: Commit**

```bash
git add src/concierge/agents/definitions.py tests/test_agent_definitions.py
git commit -m "feat: adk agent definitions from existing system prompts"
```

---

### Task 4: Facades I — Extractor, CanvasUpdater, Reconciler (+ fake_executor)

**Files:**
- Modify: `src/concierge/extractor.py`, `src/concierge/updater.py`, `src/concierge/reconciler.py`
- Modify: `tests/conftest.py` (add `fake_executor`), `tests/test_extractor.py`, `tests/test_updater.py`, `tests/test_reconciler.py`

**Interfaces:**
- Consumes: `AgentExecutor.run_validated(agent, user_text, schema)`.
- Produces: each unit's constructor becomes `__init__(self, executor, agent=None)` (agent optional so tests may pass `None`; the facade forwards it to the executor untouched). Public methods and return semantics IDENTICAL. The user-prompt строение unchanged (incl. `REFERENCE MATERIAL:` blocks). `fake_executor` conftest factory:

```python
class FakeExecutor:
    def __init__(self, results=None):
        self._results = list(results or [])
        self.calls = []

    def run_validated(self, agent, user_text, schema):
        self.calls.append((getattr(agent, "name", agent), user_text, schema))
        return self._results.pop(0) if self._results else None

    def run_text(self, agent, user_text):
        self.calls.append((getattr(agent, "name", agent), user_text, None))
        return self._results.pop(0) if self._results else None


@pytest.fixture
def fake_executor():
    def _make(results=None):
        return FakeExecutor(results=results)
    return _make
```

- [ ] **Step 1: Add `fake_executor` to conftest** (code above; keep `fake_llm` in place — later tasks still use it until Task 7).

- [ ] **Step 2: Migrate the three facades.** Pattern (Extractor shown in full; apply the same mechanical change to the other two — constructor + `call_validated(...)` → `self.executor.run_validated(self.agent, ...)`):

`extractor.py` becomes:

```python
from concierge.models import ExtractionResult

SYSTEM = (
    "You extract strategic items from a startup team's chat. "
    "Return JSON {\"items\": [{\"type\": one of "
    "decision|hypothesis|premise|risk|task|learning, "
    "\"content\": short statement, \"confidence\": 0..1}]}. "
    "Only include substantive strategic content; skip small talk."
)


class Extractor:
    def __init__(self, executor, agent=None):
        self.executor = executor
        self.agent = agent

    def extract(self, messages, context=""):
        transcript = "\n".join(f"{m['author']}: {m['text']}" for m in messages)
        if context:
            transcript += f"\n\nREFERENCE MATERIAL:\n{context}"
        result = self.executor.run_validated(
            self.agent, transcript, ExtractionResult
        )
        if result is None:
            return []
        return result.items
```

`updater.py`: same constructor; `update(...)` body keeps prompt building + BMC filter; the call becomes `self.executor.run_validated(self.agent, user, CanvasUpdateResult)`.
`reconciler.py`: same constructor; `reconcile(...)` keeps known_ids/_ALLOWED filters; call becomes `self.executor.run_validated(self.agent, user, ReconciliationResult)`.
(Remove the now-unused `from concierge.llm.client import call_validated` import in each.)

- [ ] **Step 3: Migrate their tests.** Replace `fake_llm` usage; assertion targets change from `llm.calls[0][1]` to `ex.calls[0][1]` (user text). Example (`tests/test_extractor.py` full new content):

```python
from concierge.extractor import Extractor
from concierge.models import ExtractionResult, ExtractedItem, ItemType


def test_extract_returns_items(fake_executor):
    ex = fake_executor(results=[ExtractionResult(items=[
        ExtractedItem(type=ItemType.DECISION, content="Target SMBs",
                      confidence=0.9)])])
    items = Extractor(ex).extract(
        [{"author": "ana", "text": "let's focus on small businesses"}])
    assert len(items) == 1 and items[0].type == ItemType.DECISION
    assert "small businesses" in ex.calls[0][1]


def test_extract_returns_empty_on_none(fake_executor):
    ex = fake_executor(results=[None])
    assert Extractor(ex).extract([{"author": "a", "text": "hi"}]) == []


def test_extract_appends_reference_material(fake_executor):
    ex = fake_executor(results=[ExtractionResult(items=[])])
    Extractor(ex).extract([{"author": "ana", "text": "oi"}],
                          context="use o método X")
    assert "REFERENCE MATERIAL:\nuse o método X" in ex.calls[0][1]
```

Migrate `test_updater.py` and `test_reconciler.py` with the same mechanical translation (results are `CanvasUpdateResult(blocks=[...])` / `ReconciliationResult(transitions=[...])` instances or `None`; keep every existing behavioral assertion — BMC filter, unknown-id drop, allowed-status drop, reference-material block).

- [ ] **Step 4: Fix the two construction sites that break** — `tests/test_orchestrator.py` builds `Extractor(extractor_llm)` etc. with fake LLMs. Update ONLY the constructions in that file: replace each `Extractor(fake_llm(responses=[X]))` with `Extractor(fake_executor(results=[<validated instance of X>]))` — the orchestrator fixtures translate their canned dict responses into model instances (`ExtractionResult.model_validate({...})` etc.). `test_materials.py`'s `MaterialService` and `test_bot.py`'s `_orch` also construct units with `fake_llm` — those keep working untouched ONLY if their modules aren't migrated yet; `materials.classify` and `participant`/`guardian`/`stylist` are Task 5, so in THIS task update just the extractor/updater/reconciler constructions wherever they appear (orchestrator + bot helpers).

- [ ] **Step 5: Run** — `pytest -q` (expect 146 passed, all green).

- [ ] **Step 6: Commit**

```bash
git add src/concierge/extractor.py src/concierge/updater.py src/concierge/reconciler.py tests/
git commit -m "refactor: extractor/updater/reconciler become adk-executor facades"
```

---

### Task 5: Facades II — Guardian, Participant, Stylist, classify

**Files:**
- Modify: `src/concierge/guardian.py`, `src/concierge/participant.py`, `src/concierge/stylist.py`, `src/concierge/materials.py`
- Modify: `tests/test_guardian.py`, `tests/test_participant.py`, `tests/test_stylist.py`, `tests/test_materials.py`, plus remaining constructions in `tests/test_orchestrator.py`/`tests/test_bot.py`.

**Interfaces:**
- Consumes: `run_validated`; `fake_executor`.
- Produces (contracts identical, constructors gain executor):
  - `Guardian(executor, agent=None)` — `looks_strategic` UNCHANGED (pure). `check(text, known_items, method_context="", style="")`: user prompt as today; **style moves to a user-prompt suffix**: when non-empty append `f"\n\nWrite the 'reason' field in this voice: {style}"`. Call: `run_validated(self.agent, user, CoherenceVerdict)`.
  - `Participant(executor, consider_agent=None, respond_agent=None)` — `consider(...)` appends style suffix `f"\n\nWrite in this voice: {style}"` to the user prompt when non-empty; validates `Contribution` (+ `_unwrap_text` kept). `respond(...)` same suffix; validates `StyledText`, returns unwrapped `.text` or None.
  - `Stylist(executor, agent=None)` — `restyle(text, personality)`: empty personality → passthrough (no executor call); else `run_validated(self.agent, f"VOICE:\n{personality}\n\nMESSAGE:\n{text}", StyledText)`, fallback to original text on None.
  - `materials.classify(executor, agent, filename, text) -> MaterialType` (signature changes from `classify(llm, ...)`); `MaterialService(executor, agent, knowledge, storage)` internally uses it. GENERIC fallback preserved.
  - `Orchestrator` construction sites and `main.py` are Task 6 — in THIS task update the remaining test fixtures (`_orch_with_guardian`, `_orch`, `_FakeParticipant` untouched, `MaterialService` tests) to the new constructors.

- [ ] **Step 1: Migrate the four modules** (mechanical: constructor + executor call + style-to-user-prompt). Guardian's `check` full new body:

```python
    def check(self, text, known_items, method_context="", style=""):
        items_txt = "\n".join(f"[{i['type']}] {i['content']}" for i in known_items)
        user = (
            f"NEW MESSAGE:\n{text}\n\n"
            f"KNOWN ITEMS:\n{items_txt}\n\n"
            f"METHOD CONTEXT:\n{method_context}"
        )
        if style:
            user += f"\n\nWrite the 'reason' field in this voice: {style}"
        return self.executor.run_validated(self.agent, user, CoherenceVerdict)
```

- [ ] **Step 2: Migrate the tests** — same translation as Task 4; the style tests now assert the voice string in `ex.calls[0][1]` (user text) instead of the system prompt. Keep EVERY behavioral assertion (prefilter LLM-free with `Guardian(None)`; verdict passthrough; None-silence; unwrap double-encoded JSON; presets set; truncation etc.). For `test_orchestrator.py`: `_orch_with_guardian(guardian_llm)` becomes `_orch_with_guardian(guardian_executor)` building `Guardian(guardian_executor)`; canned dicts become `CoherenceVerdict.model_validate({...})` instances. `test_check_coherence_passes_personality_as_style` asserts the voice appears in `ex.calls[0][1]`.

- [ ] **Step 3: Run** — `pytest -q` (expect 146 passed).

- [ ] **Step 4: Commit**

```bash
git add src/concierge/guardian.py src/concierge/participant.py src/concierge/stylist.py src/concierge/materials.py tests/
git commit -m "refactor: guardian/participant/stylist/classifier become adk facades"
```

---

### Task 6: MessageFunnelAgent + orchestrator on ADK

**Files:**
- Create: `src/concierge/agents/funnel.py`
- Create: `tests/test_funnel.py`
- Modify: `src/concierge/orchestrator.py`, `tests/test_orchestrator.py`

**Interfaces:**
- Consumes: verified custom-BaseAgent pattern (spike), facades.
- Produces:
  - `MessageFunnelAgent(BaseAgent)` with `sub_agents=[guardian_agent, consider_agent]` and pydantic fields `confidence_threshold: float`, `participation_threshold: float`. `_run_async_impl(ctx)` reads `ctx.session.state`: `gates` (dict: `silent: bool`, `participation_ok: bool` — cooldown+enabled+prefilter pre-computed), `guardian_user` (prompt), `consider_user` (prompt). Flow: if `silent` → `state["result"]={"decision":"none"}`; else run guardian sub-agent with `guardian_user`, parse `CoherenceVerdict` from its final text (json; parse failure → treat as no-verdict): contradicts & conf ≥ threshold → `result={"decision":"alert","reason":...,"confidence":...,"item_content":...}`; else if `participation_ok` → run consider sub-agent, parse `Contribution`: should_contribute & relevance ≥ threshold & text → `result={"decision":"contribution","text":...}`; else `result={"decision":"none"}`. To feed each sub-agent its own prompt, the funnel sets `ctx.session.state["_user"]` and the sub-agents are built with instruction as-is while the funnel passes the prompt by yielding a user-content event... **Simplification (binding):** the funnel does NOT re-route content through sub_agent.run_async; instead it receives an injected `executor`-style callable? NO — keep it pure ADK: the funnel builds `types.Content` and invokes `sub.run_async(ctx)` after writing the prompt into `ctx.session.state["guardian_user"/"consider_user"]`, with each LlmAgent's instruction extended at build time by `" Respond to the request in session state."`… **This is exactly the seam Task 1's spike may correct.** The PRAGMATIC binding contract for this task (works regardless): `MessageFunnelAgent` holds plain references `guardian_facade`/`participant_facade` (`model_config = {"arbitrary_types_allowed": True}`) and calls them inside `_run_async_impl` (they are sync; wrap in `asyncio.to_thread`), yielding a single final Event whose text is the JSON of `result`, and writing `ctx.session.state["result"]`. Gates stay deterministic code inside the ADK agent graph; the LLM work happens in the facades' agents via the executor. This keeps "orquestração como agente ADK" honest AND type-safe.
  - Orchestrator: constructor unchanged in shape but gains `funnel_executor` internals: `check_coherence` and `participate` keep signatures/behavior; internally both now go through `self._run_funnel(project_id, message_id, text)` which pre-computes gates + prompts context (same storage reads as today), runs the funnel agent via `AgentExecutor.run_text` (session state seeded via... simplest: funnel invoked directly: `asyncio` not needed — since facades are sync, orchestrator calls a plain `funnel.decide(gates, inputs)` **helper method on the agent class** used both by `_run_async_impl` and callable synchronously). `check_coherence` returns the alert string only for `decision=="alert"` (and records the intervention); `participate` returns text only for `decision=="contribution"` (and updates the cooldown marker). To avoid double LLM runs when bot calls check_coherence then participate: orchestrator caches the last funnel result per (project_id, message_id) in `self._last_funnel`.
- The binding, non-negotiable assertions for review: funnel gates ordering (silent → guardian → participation), one voice, thresholds honored, `decide` never raises, orchestrator contracts byte-compatible for bot.py.

- [ ] **Step 1: Write the failing tests** — `tests/test_funnel.py`:

```python
from concierge.agents.funnel import MessageFunnelAgent
from concierge.models import CoherenceVerdict, Contribution


class _G:  # guardian facade stub
    def __init__(self, verdict):
        self.verdict = verdict
        self.calls = []

    def check(self, text, known_items, method_context="", style=""):
        self.calls.append(text)
        return self.verdict


class _P:  # participant facade stub
    def __init__(self, contribution):
        self.contribution = contribution
        self.calls = []

    def consider(self, window, items, materials, style=""):
        self.calls.append(window)
        return self.contribution


def _funnel(verdict=None, contribution=None, ct=0.75, pt=0.75):
    return MessageFunnelAgent(
        name="funnel", guardian_facade=_G(verdict), participant_facade=_P(contribution),
        confidence_threshold=ct, participation_threshold=pt,
    )


def _inputs(**kw):
    base = dict(text="vamos priorizar enterprise", known_items=[], window=[],
                items=[], materials_guardian="", materials_participant="",
                style="")
    base.update(kw)
    return base


def test_silent_gate_short_circuits():
    f = _funnel(verdict=CoherenceVerdict(contradicts=True, reason="x",
                                         confidence=0.9))
    out = f.decide(gates={"silent": True, "participation_ok": True}, **_inputs())
    assert out == {"decision": "none"}
    assert f.guardian_facade.calls == []


def test_guardian_alert_wins_and_participant_never_runs():
    f = _funnel(
        verdict=CoherenceVerdict(contradicts=True, item_content="X",
                                 reason="conflita", confidence=0.9),
        contribution=Contribution(should_contribute=True, relevance=0.9,
                                  kind="question", text="?"),
    )
    out = f.decide(gates={"silent": False, "participation_ok": True}, **_inputs())
    assert out["decision"] == "alert" and out["confidence"] == 0.9
    assert f.participant_facade.calls == []


def test_low_confidence_falls_through_to_participant():
    f = _funnel(
        verdict=CoherenceVerdict(contradicts=True, reason="meh", confidence=0.5),
        contribution=Contribution(should_contribute=True, relevance=0.9,
                                  kind="connection", text="liga com X"),
    )
    out = f.decide(gates={"silent": False, "participation_ok": True}, **_inputs())
    assert out == {"decision": "contribution", "text": "liga com X"}


def test_participation_gate_blocks_consider():
    f = _funnel(verdict=None, contribution=Contribution(
        should_contribute=True, relevance=0.9, kind="question", text="?"))
    out = f.decide(gates={"silent": False, "participation_ok": False}, **_inputs())
    assert out == {"decision": "none"}
    assert f.participant_facade.calls == []


def test_never_raises_on_none_verdict_and_contribution():
    f = _funnel(verdict=None, contribution=None)
    out = f.decide(gates={"silent": False, "participation_ok": True}, **_inputs())
    assert out == {"decision": "none"}
```

- [ ] **Step 2: Implement `src/concierge/agents/funnel.py`**:

```python
import json

from google.adk.agents.base_agent import BaseAgent
from google.genai import types

try:  # Event import location per spike
    from google.adk.events import Event
except ImportError:  # pragma: no cover
    from google.adk.events.event import Event


class MessageFunnelAgent(BaseAgent):
    """Deterministic ADK orchestrator for the non-mention message path.

    Gates and priority are code; the LLM work happens in the guardian and
    participant facades (each backed by its own ADK LlmAgent + executor).
    """

    model_config = {"arbitrary_types_allowed": True}

    guardian_facade: object
    participant_facade: object
    confidence_threshold: float = 0.75
    participation_threshold: float = 0.75

    def decide(self, gates, text, known_items, window, items,
               materials_guardian, materials_participant, style):
        if gates.get("silent"):
            return {"decision": "none"}
        verdict = self.guardian_facade.check(
            text, known_items, materials_guardian, style=style
        )
        if (verdict is not None and verdict.contradicts
                and verdict.confidence >= self.confidence_threshold):
            return {
                "decision": "alert",
                "reason": verdict.reason,
                "confidence": verdict.confidence,
                "item_content": verdict.item_content,
            }
        if not gates.get("participation_ok"):
            return {"decision": "none"}
        c = self.participant_facade.consider(
            window, items, materials_participant, style=style
        )
        if (c is not None and c.should_contribute
                and c.relevance >= self.participation_threshold
                and c.text.strip()):
            return {"decision": "contribution", "text": c.text}
        return {"decision": "none"}

    async def _run_async_impl(self, ctx):
        import asyncio

        state = ctx.session.state
        result = await asyncio.to_thread(
            self.decide,
            gates=state.get("gates", {}),
            text=state.get("text", ""),
            known_items=state.get("known_items", []),
            window=state.get("window", []),
            items=state.get("items", []),
            materials_guardian=state.get("materials_guardian", ""),
            materials_participant=state.get("materials_participant", ""),
            style=state.get("style", ""),
        )
        state["result"] = result
        yield Event(
            author=self.name,
            content=types.Content(
                role="model", parts=[types.Part(text=json.dumps(result))]
            ),
        )
```

(Adjust the `Event` construction per the spike's findings if needed.)

- [ ] **Step 3: Rewire `src/concierge/orchestrator.py`.** Constructor unchanged. Add funnel construction + result cache; `check_coherence`/`participate` delegate. Replace both methods and add helpers:

```python
    def _funnel(self):
        if getattr(self, "_funnel_agent", None) is None:
            from concierge.agents.funnel import MessageFunnelAgent

            self._funnel_agent = MessageFunnelAgent(
                name="message_funnel",
                guardian_facade=self.guardian,
                participant_facade=self.participant,
                confidence_threshold=self.settings.confidence_threshold,
                participation_threshold=self.settings.participation_threshold,
            )
        return self._funnel_agent

    def _run_funnel(self, project_id, message_id, text):
        key = (project_id, message_id)
        cached = getattr(self, "_last_funnel", None)
        if cached and cached[0] == key:
            return cached[1]
        gates = {
            "silent": self.storage.get_mode(project_id) == ProjectMode.SILENT,
            "participation_ok": self._participation_ok(project_id, text),
        }
        known = self.storage.items_by_status(
            project_id, [ItemStatus.VALIDATED, ItemStatus.DISCARDED]
        )
        window, items, materials_p, style = self._participant_context(
            project_id, text
        )
        materials_g = ""
        if self.knowledge is not None:
            materials_g = self.knowledge.query(
                project_id, text, material_types=types_for_module("guardian")
            )
        if not self.guardian.looks_strategic(text):
            result = {"decision": "none"}
        else:
            result = self._funnel().decide(
                gates=gates, text=text, known_items=known, window=window,
                items=items, materials_guardian=materials_g,
                materials_participant=materials_p, style=style,
            )
        self._last_funnel = (key, result)
        return result

    def _participation_ok(self, project_id, text):
        if self.participant is None or not self.settings.participation_enabled:
            return False
        marker = self.storage.get_last_participation(project_id)
        if (marker is not None and
                self.storage.messages_since(project_id, marker)
                < self.settings.participation_cooldown):
            return False
        return len(text) >= 20

    def check_coherence(self, project_id, message_id, text):
        result = self._run_funnel(project_id, message_id, text)
        if result["decision"] != "alert":
            return None
        self.storage.add_intervention(
            project_id, message_id, None, result["reason"], result["confidence"]
        )
        return (
            "⚠️ Atenção à coerência estratégica:\n"
            f"{result['reason']}\n"
            f"(item relacionado: {result['item_content']})"
        )

    def participate(self, project_id, message_id, text):
        result = self._run_funnel(project_id, message_id, text)
        if result["decision"] != "contribution":
            return None
        window = self.storage.recent_messages(project_id, 1)
        if window:
            self.storage.set_last_participation(project_id, window[-1]["id"])
        return result["text"]
```

NOTE the behavior deltas to preserve: the cheap prefilter (`looks_strategic` + len) still runs BEFORE any LLM; SILENT still blocks the guardian; mention path (`respond_mention`) unchanged. One intentional refinement: `looks_strategic` gating now also guards the guardian (as before) and the funnel is only consulted once per message (cache) even though bot calls two methods.

- [ ] **Step 4: Migrate `tests/test_orchestrator.py`** — the existing gate/threshold/alert tests keep their assertions; constructions updated (facades with `fake_executor` results as validated instances). The `test_check_silent_on_trivial_message` LLM-zero assertion becomes `ex.calls == []` on the guardian's executor.

- [ ] **Step 5: Run** — `pytest tests/test_funnel.py tests/test_orchestrator.py -v`, then `pytest -q` (expect 151 = 146 + 5 funnel).

- [ ] **Step 6: Commit**

```bash
git add src/concierge/agents/funnel.py tests/test_funnel.py src/concierge/orchestrator.py tests/test_orchestrator.py
git commit -m "feat: deterministic adk funnel agent orchestrates the message path"
```

---

### Task 7: Wiring, llm/ removal, docs, full verification

**Files:**
- Modify: `src/concierge/main.py`, `tests/conftest.py`
- Delete: `src/concierge/llm/` (4 files), `tests/test_llm_client.py`, `tests/test_llm_factory.py`, `tests/test_openai_client.py`, `tests/test_gemini_client.py`
- Modify: `README.md`, `SETUP.md`, `DOCUMENTACAO.md` (framework mentions)

**Interfaces:**
- Consumes: everything above.
- Produces: `main.py` builds: `configure_env(settings)` → `model = agent_model(settings)` → `agents = build_agents(model)` → `executor = AgentExecutor()` → facades (`Extractor(executor, agents["extractor"])`, `CanvasUpdater(executor, agents["canvas_updater"])`, `Guardian(executor, agents["guardian"])`, `Reconciler(executor, agents["reconciler"])`, `Participant(executor, agents["participant_consider"], agents["participant_respond"])`, `Stylist(executor, agents["stylist"])`, `MaterialService(executor, agents["material_classifier"], knowledge, storage)`) → orchestrator (same kwargs as today). `_check_credentials` unchanged.

- [ ] **Step 1: Rewire `main.py`** (replace the llm imports/builds):

```python
from concierge.agents.definitions import build_agents
from concierge.agents.executor import AgentExecutor
from concierge.agents.model_factory import agent_model, configure_env
```

and in `main()` replace `llm = build_llm(settings)` with:

```python
    configure_env(settings)
    model = agent_model(settings)
    agents = build_agents(model)
    executor = AgentExecutor()
```

then update every facade construction to the new signatures (listed in Interfaces).

- [ ] **Step 2: Delete the old layer**

```bash
git rm -r src/concierge/llm tests/test_llm_client.py tests/test_llm_factory.py tests/test_openai_client.py tests/test_gemini_client.py
```

Remove `fake_llm` fixture + `FakeLLMClient` import from `tests/conftest.py`. `grep -rn "concierge.llm" src tests` must return nothing.

- [ ] **Step 3: Full suite + smokes**

Run: `pytest -q` — all green (151 minus the ~13 deleted llm tests ≈ 138; record exact count).
Run: `PYTHONPATH=src python -c "import concierge.main; from concierge.agents.funnel import MessageFunnelAgent; print('ok')"` → `ok`.

- [ ] **Step 4: Docs** — README tech list and DOCUMENTACAO §4/§7 + SETUP prerequisites: mention **Google ADK (LlmAgents + Runner + funnel agent determinístico)** as the agent framework; provider mapping unchanged (`LLM_PROVIDER`), note `google-adk`/`litellm` pins.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat: google adk is the agent framework; legacy llm layer removed"
```

---

## Self-Review

**Spec coverage:** §2 model_factory/definitions/executor/funnel → T1/T3/T2/T6; fachadas → T4/T5; orchestrator/pipeline → T6 (sync pipeline already runs through facades — no change needed beyond construction); llm/ removal + main + docs → T7; §3 FakeAdkModel/fake_executor → T1/T2/T4; §4 voice-to-user-prompt → T5; §5 invariantes → asserted across T2 (retry/None), T6 (gates/priority/one-voice/prefilter-zero-LLM); §6 pins → T1; §7 spike-corrects-plan → T1 constraint. ✓

**Placeholders:** the funnel/orchestrator code in T6 is complete; T1 explicitly authorizes API adaptations with mandatory reporting. One deliberate hybrid documented in T6's Interfaces (facades called from inside the ADK agent). ✓

**Type consistency:** `AgentExecutor.run_validated(agent, user_text, schema)` used identically in T2/T4/T5; facade constructors `(executor, agent=None)` (Participant takes two agents; MaterialService `(executor, agent, knowledge, storage)`); `decide(gates=..., text=..., known_items=..., window=..., items=..., materials_guardian=..., materials_participant=..., style=...)` matches T6 tests; `FakeAdkModel` imported from the spike in T2/T3. ✓
