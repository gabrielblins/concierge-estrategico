# Conversation Participant Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The bot becomes a conversation participant — always answers mentions, and rarely (three gates) contributes spontaneously with connections, material knowledge, socratic questions, or synthesis, in the project's configured voice.

**Architecture:** A new `Participant` unit (pattern of Guardian/Extractor: wraps LLMClient, `call_validated`, Pydantic schema) decides-and-generates in one call. The Orchestrator gains `participate()` (proactive, 3 gates: config/cooldown → cheap prefilter → LLM self-assessed relevance) and `respond_mention()`. `on_message` reorders: mention → respond (skip guardian); else guardian first, participant only if guardian stayed silent. Cooldown persists in `projects.last_participation_msg_id`.

**Tech Stack:** Python 3.14, existing LLMClient/call_validated, Pydantic, SQLite, existing typed-RAG (`types_for_module`).

## Global Constraints

- One voice per message: mention path skips the guardian; proactive path runs only when the guardian returned no alert.
- Proactive gates in order: (1) `participation_enabled` AND mode ≠ silent AND messages since last participation ≥ `participation_cooldown` (default 10); (2) cheap prefilter `looks_strategic(text) and len(text) >= 20` (no LLM); (3) `should_contribute` AND `relevance >= participation_threshold` (default 0.75).
- LLM failure/invalid → `None` → silence in BOTH paths (the bot never posts errors).
- Style (personality) is injected into the participant's SYSTEM prompt (same mechanic as the guardian); no Stylist call.
- Backward compatible: `Orchestrator(..., participant=None)` default; `knowledge=None` supported; existing 99 tests keep passing.
- Env names exactly: `PARTICIPATION_ENABLED` (default true; "false" disables), `PARTICIPATION_COOLDOWN` (default 10), `PARTICIPATION_THRESHOLD` (default 0.75).
- All LLM calls via `call_validated`. All business logic testable without network.
- Shared venv: `. .venv/bin/activate` at repo root (Python 3.14.3). Suite currently at 99 passed.

---

## File Structure

```
src/concierge/
  participant.py    # NEW: Participant.consider / .respond, prompts
  models.py         # +ContributionKind, +Contribution
  config.py         # +participation_enabled/cooldown/threshold
  storage.py        # +recent_messages, +last_participation col+get/set, +messages_since
  materials.py      # ROUTING: "participant" added to all 5 types
  orchestrator.py   # +participant kwarg, +participate(), +respond_mention()
  bot.py            # +_is_mention, on_message reorder
  main.py           # builds Participant, passes to Orchestrator
tests/
  test_participant.py  # NEW
  + additions to test_config/test_models/test_storage/test_materials/
    test_orchestrator/test_bot
.env.example        # +3 vars
README.md, SETUP.md # participant behavior noted
```

---

### Task 1: Config and models

**Files:**
- Modify: `src/concierge/config.py`, `src/concierge/models.py`, `.env.example`
- Modify: `tests/test_config.py`, `tests/test_models.py`

**Interfaces:**
- Produces: `Settings.participation_enabled: bool = True` (env `PARTICIPATION_ENABLED`, string "false" case-insensitive → False, anything else → True), `participation_cooldown: int = 10` (env `PARTICIPATION_COOLDOWN`), `participation_threshold: float = 0.75` (env `PARTICIPATION_THRESHOLD`). `ContributionKind(str, Enum)`: `connection`, `knowledge`, `question`, `synthesis`. `Contribution(BaseModel)`: `should_contribute: bool`, `relevance: float`, `kind: ContributionKind | None = None`, `text: str = ""`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_config.py`:

```python
def test_settings_participation_fields(monkeypatch):
    monkeypatch.setenv("TELEGRAM_TOKEN", "tok")
    monkeypatch.setenv("OPENAI_API_KEY", "okey")
    monkeypatch.delenv("PARTICIPATION_ENABLED", raising=False)
    monkeypatch.delenv("PARTICIPATION_COOLDOWN", raising=False)
    monkeypatch.delenv("PARTICIPATION_THRESHOLD", raising=False)
    s = Settings.from_env()
    assert s.participation_enabled is True
    assert s.participation_cooldown == 10
    assert s.participation_threshold == 0.75
    monkeypatch.setenv("PARTICIPATION_ENABLED", "False")
    monkeypatch.setenv("PARTICIPATION_COOLDOWN", "3")
    monkeypatch.setenv("PARTICIPATION_THRESHOLD", "0.5")
    s2 = Settings.from_env()
    assert s2.participation_enabled is False
    assert s2.participation_cooldown == 3
    assert s2.participation_threshold == 0.5
```

Append to `tests/test_models.py`:

```python
def test_contribution_schema_and_kinds():
    from concierge.models import Contribution, ContributionKind
    assert {k.value for k in ContributionKind} == {
        "connection", "knowledge", "question", "synthesis"
    }
    c = Contribution.model_validate({
        "should_contribute": True, "relevance": 0.9,
        "kind": "question", "text": "Qual evidência sustenta isso?",
    })
    assert c.kind == ContributionKind.QUESTION
    quiet = Contribution.model_validate({"should_contribute": False, "relevance": 0.1})
    assert quiet.kind is None and quiet.text == ""
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_config.py tests/test_models.py -v -k "participation or contribution"`
Expected: FAIL (`AttributeError: participation_enabled` / `ImportError: Contribution`)

- [ ] **Step 3: Implement**

`config.py` — add fields to the dataclass (after `gemini_model`):

```python
    participation_enabled: bool = True
    participation_cooldown: int = 10
    participation_threshold: float = 0.75
```

and in `from_env()` (after the gemini lines):

```python
            participation_enabled=(
                os.environ.get("PARTICIPATION_ENABLED", "true").lower() != "false"
            ),
            participation_cooldown=int(os.environ.get("PARTICIPATION_COOLDOWN", "10")),
            participation_threshold=float(
                os.environ.get("PARTICIPATION_THRESHOLD", "0.75")
            ),
```

`models.py` — append:

```python
class ContributionKind(str, Enum):
    CONNECTION = "connection"
    KNOWLEDGE = "knowledge"
    QUESTION = "question"
    SYNTHESIS = "synthesis"


class Contribution(BaseModel):
    should_contribute: bool
    relevance: float
    kind: ContributionKind | None = None
    text: str = ""
```

`.env.example` — append under the tuning section:

```
PARTICIPATION_ENABLED=true
PARTICIPATION_COOLDOWN=10
PARTICIPATION_THRESHOLD=0.75
```

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/test_config.py tests/test_models.py -v` — PASS; then `pytest -q` (expect 101 passed).

- [ ] **Step 5: Commit**

```bash
git add src/concierge/config.py src/concierge/models.py .env.example tests/test_config.py tests/test_models.py
git commit -m "feat: participation settings and contribution schema"
```

---

### Task 2: Storage — conversation window and participation cooldown

**Files:**
- Modify: `src/concierge/storage.py`
- Modify: `tests/test_storage.py`

**Interfaces:**
- Produces:
  - `recent_messages(project_id: int, limit: int = 15) -> list[dict]` — last `limit` messages (`id, author, text`), ordered oldest→newest within the window.
  - `projects.last_participation_msg_id INTEGER` (nullable; + ALTER TABLE guard, same pattern as `personality`).
  - `set_last_participation(project_id: int, message_id: int) -> None`.
  - `get_last_participation(project_id: int) -> int | None`.
  - `messages_since(project_id: int, message_id: int | None) -> int` — count of messages with `id >` marker; `None` marker → total count.

- [ ] **Step 1: Write the failing test** — append to `tests/test_storage.py`:

```python
def test_recent_messages_window_oldest_to_newest(storage):
    pid = storage.get_or_create_project(100, "Acme")
    for i in range(1, 6):
        storage.add_message(pid, i, "ana", f"msg {i}", float(i))
    window = storage.recent_messages(pid, limit=3)
    assert [m["text"] for m in window] == ["msg 3", "msg 4", "msg 5"]
    assert set(window[0]) == {"id", "author", "text"}


def test_participation_cooldown_roundtrip(storage):
    pid = storage.get_or_create_project(100, "Acme")
    assert storage.get_last_participation(pid) is None
    m1 = storage.add_message(pid, 1, "ana", "a", 1.0)
    m2 = storage.add_message(pid, 2, "ana", "b", 2.0)
    m3 = storage.add_message(pid, 3, "ana", "c", 3.0)
    assert storage.messages_since(pid, None) == 3
    storage.set_last_participation(pid, m1)
    assert storage.get_last_participation(pid) == m1
    assert storage.messages_since(pid, m1) == 2
    assert storage.messages_since(pid, m3) == 0
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_storage.py -v -k "recent or cooldown"`
Expected: FAIL with `AttributeError: 'Storage' object has no attribute 'recent_messages'`

- [ ] **Step 3: Implement** — in `src/concierge/storage.py`:

3a. `SCHEMA`: add to the `projects` table (after `personality`):

```sql
    last_participation_msg_id INTEGER,
```

3b. `init_schema`: third migration guard next to the existing two:

```python
        try:
            self.conn.execute(
                "ALTER TABLE projects ADD COLUMN last_participation_msg_id INTEGER"
            )
        except sqlite3.OperationalError:
            pass  # column already exists
```

3c. Methods inside `Storage`:

```python
    def recent_messages(self, project_id: int, limit: int = 15) -> list[dict]:
        cur = self.conn.execute(
            "SELECT id, author, text FROM ("
            "  SELECT id, author, text FROM messages"
            "  WHERE project_id = ? ORDER BY id DESC LIMIT ?"
            ") ORDER BY id ASC",
            (project_id, limit),
        )
        return [dict(r) for r in cur.fetchall()]

    def set_last_participation(self, project_id: int, message_id: int) -> None:
        self.conn.execute(
            "UPDATE projects SET last_participation_msg_id = ? WHERE id = ?",
            (message_id, project_id),
        )
        self.conn.commit()

    def get_last_participation(self, project_id: int):
        cur = self.conn.execute(
            "SELECT last_participation_msg_id FROM projects WHERE id = ?",
            (project_id,),
        )
        row = cur.fetchone()
        return row["last_participation_msg_id"] if row else None

    def messages_since(self, project_id: int, message_id) -> int:
        if message_id is None:
            cur = self.conn.execute(
                "SELECT COUNT(*) n FROM messages WHERE project_id = ?", (project_id,)
            )
        else:
            cur = self.conn.execute(
                "SELECT COUNT(*) n FROM messages WHERE project_id = ? AND id > ?",
                (project_id, message_id),
            )
        return cur.fetchone()["n"]
```

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/test_storage.py -v` — PASS; `pytest -q` (expect 103 passed).

- [ ] **Step 5: Commit**

```bash
git add src/concierge/storage.py tests/test_storage.py
git commit -m "feat: conversation window and participation cooldown storage"
```

---

### Task 3: Participant module + routing

**Files:**
- Create: `src/concierge/participant.py`
- Modify: `src/concierge/materials.py` (ROUTING)
- Create: `tests/test_participant.py`
- Modify: `tests/test_materials.py`

**Interfaces:**
- Consumes: `call_validated`, `Contribution`, `StyledText` (existing), `ROUTING`/`types_for_module`.
- Produces:
  - `materials.ROUTING`: `"participant"` added to ALL five type sets; `types_for_module("participant")` → all 5 values sorted.
  - `Participant(llm)`:
    - `consider(window: list[dict], items: list[dict], materials: str, style: str = "") -> Contribution | None` — one call decides+generates; `call_validated` with `Contribution`; `None` on failure.
    - `respond(window, items, materials, mention_text: str, style: str = "") -> str | None` — `call_validated` with `StyledText`; returns `result.text` or `None`.
  - Both build the user prompt from: `CONVERSATION:\n{author: text lines}\n\nSTRATEGIC ITEMS:\n[type] content lines\n\nREFERENCE MATERIAL:\n{materials}` (+ `\n\nADDRESSED TO YOU:\n{mention_text}` in respond). `style` non-empty → SYSTEM suffix `" Write in this voice: {style}"`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_participant.py`:

```python
from concierge.participant import Participant
from concierge.models import ContributionKind

WINDOW = [{"id": 1, "author": "ana", "text": "e se focarmos em healthtechs?"},
          {"id": 2, "author": "bob", "text": "pode ser, mas não sei"}]
ITEMS = [{"type": "hypothesis", "content": "SMBs pagam pela economia de tempo"}]


def test_consider_returns_contribution_with_context_in_prompt(fake_llm):
    llm = fake_llm(responses=[{
        "should_contribute": True, "relevance": 0.9, "kind": "connection",
        "text": "Isso conversa com a hipótese validada de SMBs — healthtechs são um recorte dela?",
    }])
    p = Participant(llm)
    c = p.consider(WINDOW, ITEMS, "trecho do manual", style="")
    assert c.should_contribute and c.kind == ContributionKind.CONNECTION
    user = llm.calls[0][1]
    assert "healthtechs" in user and "SMBs pagam" in user and "trecho do manual" in user


def test_consider_style_injected_and_failure_silent(fake_llm):
    llm = fake_llm(responses=[{
        "should_contribute": False, "relevance": 0.1, "kind": None, "text": "",
    }])
    p = Participant(llm)
    p.consider(WINDOW, [], "", style="voz de coach")
    assert "voz de coach" in llm.calls[0][0]
    broken = Participant(fake_llm(responses=[{"bad": 1}, {"bad": 1}]))
    assert broken.consider(WINDOW, [], "") is None


def test_respond_returns_text_and_includes_mention(fake_llm):
    llm = fake_llm(responses=[{"text": "Na minha visão, vale testar com 5 clientes."}])
    p = Participant(llm)
    out = p.respond(WINDOW, ITEMS, "", "o que você acha, bot?", style="")
    assert out == "Na minha visão, vale testar com 5 clientes."
    assert "ADDRESSED TO YOU" in llm.calls[0][1]
    assert "o que você acha, bot?" in llm.calls[0][1]


def test_respond_failure_silent(fake_llm):
    p = Participant(fake_llm(responses=[{"nope": 1}, {"nope": 1}]))
    assert p.respond(WINDOW, [], "", "oi bot") is None
```

Append to `tests/test_materials.py`:

```python
def test_participant_routed_to_all_types():
    assert set(types_for_module("participant")) == {
        "canvas_guide", "validation_guide", "methodology",
        "custom_framework", "generic",
    }
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_participant.py tests/test_materials.py -v -k "participant"`
Expected: FAIL (`ModuleNotFoundError: concierge.participant`; routing assertion fails)

- [ ] **Step 3: Implement**

`materials.py` — add `"participant"` to every ROUTING set:

```python
ROUTING = {
    MaterialType.CANVAS_GUIDE: {"updater", "participant"},
    MaterialType.VALIDATION_GUIDE: {"guardian", "reconciler", "participant"},
    MaterialType.METHODOLOGY: {"extractor", "guardian", "participant"},
    MaterialType.CUSTOM_FRAMEWORK: {"extractor", "updater", "guardian", "reconciler", "participant"},
    MaterialType.GENERIC: {"guardian", "participant"},
}
```

Create `src/concierge/participant.py`:

```python
from concierge.llm.client import call_validated
from concierge.models import Contribution, StyledText

CONSIDER_SYSTEM = (
    "You are a thoughtful member of a startup team's group chat. Given the "
    "recent conversation, the team's strategic items, and reference material, "
    "decide whether you have ONE contribution that genuinely adds value. Kinds: "
    "connection (link what's being said to an existing strategic item), "
    "knowledge (bring a relevant point from the reference material), "
    "question (a socratic question that deepens a shallow discussion), "
    "synthesis (summarize positions when a topic drags on). "
    "If nothing truly adds value, return should_contribute=false. Never repeat "
    "what was just said. Return JSON {\"should_contribute\": bool, "
    "\"relevance\": 0..1, \"kind\": connection|knowledge|question|synthesis or null, "
    "\"text\": the contribution, 1-3 sentences, in the conversation's language}."
)

RESPOND_SYSTEM = (
    "You are a helpful member of a startup team's group chat and someone "
    "addressed you directly. Answer conversationally and concisely using the "
    "recent conversation, the team's strategic items, and the reference "
    "material. Answer in the conversation's language. "
    "Return JSON {\"text\": your reply}."
)


def _context(window, items, materials):
    convo = "\n".join(f"{m['author']}: {m['text']}" for m in window)
    items_txt = "\n".join(f"[{i['type']}] {i['content']}" for i in items)
    return (
        f"CONVERSATION:\n{convo}\n\n"
        f"STRATEGIC ITEMS:\n{items_txt}\n\n"
        f"REFERENCE MATERIAL:\n{materials}"
    )


class Participant:
    def __init__(self, llm):
        self.llm = llm

    def _system(self, base, style):
        return base + (f" Write in this voice: {style}" if style else "")

    def consider(self, window, items, materials, style=""):
        return call_validated(
            self.llm, self._system(CONSIDER_SYSTEM, style),
            _context(window, items, materials), Contribution,
        )

    def respond(self, window, items, materials, mention_text, style=""):
        user = _context(window, items, materials) + f"\n\nADDRESSED TO YOU:\n{mention_text}"
        result = call_validated(
            self.llm, self._system(RESPOND_SYSTEM, style), user, StyledText
        )
        return result.text if result is not None else None
```

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/test_participant.py tests/test_materials.py -v` — PASS; `pytest -q` (expect 108 passed).

- [ ] **Step 5: Commit**

```bash
git add src/concierge/participant.py src/concierge/materials.py tests/test_participant.py tests/test_materials.py
git commit -m "feat: participant module and routing to all material types"
```

---

### Task 4: Orchestrator — participate() and respond_mention()

**Files:**
- Modify: `src/concierge/orchestrator.py`
- Modify: `tests/test_orchestrator.py`

**Interfaces:**
- Consumes: Tasks 1–3 (settings fields, storage methods, `Participant`, `types_for_module("participant")`).
- Produces:
  - `Orchestrator.__init__(..., reconciler=None, participant=None)` — stores `self.participant`.
  - `participate(project_id, message_id, text) -> str | None` — gates per Global Constraints; on success calls `set_last_participation(project_id, message_id)` and returns `contribution.text`.
  - `respond_mention(project_id, message_id, text) -> str | None` — no gates beyond `participant is None`; builds the same context.
  - Both build: `window = storage.recent_messages(project_id, 15)`; `items = items_by_status([ACTIVE, VALIDATED])`; `materials = knowledge.query(project_id, text, material_types=types_for_module("participant"))` when knowledge set, else `""`; `style = get_personality(project_id)`.

- [ ] **Step 1: Write the failing test** — append to `tests/test_orchestrator.py`:

```python
class _FakeParticipant:
    def __init__(self, contribution=None, reply=None):
        self.contribution = contribution
        self.reply = reply
        self.consider_calls = []
        self.respond_calls = []

    def consider(self, window, items, materials, style=""):
        self.consider_calls.append((window, items, materials, style))
        return self.contribution

    def respond(self, window, items, materials, mention_text, style=""):
        self.respond_calls.append((window, items, materials, mention_text, style))
        return self.reply


def _orch_with_participant(fake_llm, participant, **settings_kw):
    conn = sqlite3.connect(":memory:")
    s = Storage(conn); s.init_schema()
    kw = dict(telegram_token="t", openai_api_key="k",
              participation_cooldown=2, participation_threshold=0.75)
    kw.update(settings_kw)
    settings = Settings(**kw)
    return Orchestrator(
        storage=s, extractor=None, updater=None,
        guardian=Guardian(llm=None), knowledge=None, settings=settings,
        participant=participant,
    )


def _seed(o, n):
    pid = o.storage.get_or_create_project(100, "Acme")
    for i in range(1, n + 1):
        o.storage.add_message(pid, i, "ana", f"vamos priorizar o segmento {i}", float(i))
    return pid


def test_participate_gates_before_llm(fake_llm):
    from concierge.models import Contribution, ProjectMode
    good = Contribution(should_contribute=True, relevance=0.9,
                        kind="question", text="E a evidência?")
    # enabled=False
    p = _FakeParticipant(contribution=good)
    o = _orch_with_participant(fake_llm, p, participation_enabled=False)
    pid = _seed(o, 3)
    assert o.participate(pid, 3, "vamos priorizar enterprise") is None
    # silent mode
    p2 = _FakeParticipant(contribution=good)
    o2 = _orch_with_participant(fake_llm, p2)
    pid2 = _seed(o2, 3)
    o2.storage.set_mode(pid2, ProjectMode.SILENT)
    assert o2.participate(pid2, 3, "vamos priorizar enterprise") is None
    # cooldown not elapsed (cooldown=2; only 1 message since marker)
    p3 = _FakeParticipant(contribution=good)
    o3 = _orch_with_participant(fake_llm, p3)
    pid3 = _seed(o3, 3)
    o3.storage.set_last_participation(pid3, 2)
    assert o3.participate(pid3, 3, "vamos priorizar enterprise") is None
    # prefilter: trivial text
    p4 = _FakeParticipant(contribution=good)
    o4 = _orch_with_participant(fake_llm, p4)
    pid4 = _seed(o4, 3)
    assert o4.participate(pid4, 3, "kkk ok") is None
    # none of the gated cases reached the LLM stage
    assert p.consider_calls == p2.consider_calls == p3.consider_calls == p4.consider_calls == []


def test_participate_threshold_and_success_updates_cooldown(fake_llm):
    from concierge.models import Contribution
    weak = Contribution(should_contribute=True, relevance=0.5, kind="question", text="?")
    p = _FakeParticipant(contribution=weak)
    o = _orch_with_participant(fake_llm, p)
    pid = _seed(o, 3)
    assert o.participate(pid, 3, "vamos priorizar o segmento enterprise") is None
    strong = Contribution(should_contribute=True, relevance=0.9,
                          kind="connection", text="Isso liga com a hipótese X.")
    p2 = _FakeParticipant(contribution=strong)
    o2 = _orch_with_participant(fake_llm, p2)
    pid2 = _seed(o2, 3)
    out = o2.participate(pid2, 3, "vamos priorizar o segmento enterprise")
    assert out == "Isso liga com a hipótese X."
    assert o2.storage.get_last_participation(pid2) == 3
    # window and personality were assembled
    window, items, materials, style = p2.consider_calls[0]
    assert len(window) == 3 and materials == ""


def test_respond_mention_no_gates_and_style(fake_llm):
    p = _FakeParticipant(reply="Na minha visão, testem com 5 clientes.")
    o = _orch_with_participant(fake_llm, p, participation_enabled=False)
    pid = _seed(o, 2)
    o.storage.set_personality(pid, "voz de mentor")
    out = o.respond_mention(pid, 2, "bot, o que acha?")
    assert out == "Na minha visão, testem com 5 clientes."
    _, _, _, mention, style = p.respond_calls[0]
    assert mention == "bot, o que acha?" and style == "voz de mentor"


def test_participate_none_participant_is_silent(fake_llm):
    o = _orch_with_participant(fake_llm, None)
    pid = _seed(o, 3)
    assert o.participate(pid, 3, "vamos priorizar enterprise") is None
    assert o.respond_mention(pid, 3, "bot?") is None
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_orchestrator.py -v -k "participate or respond_mention"`
Expected: FAIL with `TypeError: __init__() got an unexpected keyword argument 'participant'`

- [ ] **Step 3: Implement** — in `src/concierge/orchestrator.py`:

3a. Constructor: `def __init__(self, storage, extractor, updater, guardian, knowledge, settings, reconciler=None, participant=None):` and `self.participant = participant`.

3b. New methods (after `check_coherence`):

```python
    def _participant_context(self, project_id, text):
        window = self.storage.recent_messages(project_id, 15)
        items = self.storage.items_by_status(
            project_id, [ItemStatus.ACTIVE, ItemStatus.VALIDATED]
        )
        materials = ""
        if self.knowledge is not None:
            materials = self.knowledge.query(
                project_id, text, material_types=types_for_module("participant")
            )
        style = self.storage.get_personality(project_id)
        return window, items, materials, style

    def participate(self, project_id, message_id, text):
        if self.participant is None or not self.settings.participation_enabled:
            return None
        if self.storage.get_mode(project_id) == ProjectMode.SILENT:
            return None
        marker = self.storage.get_last_participation(project_id)
        if (marker is not None and
                self.storage.messages_since(project_id, marker)
                < self.settings.participation_cooldown):
            return None
        if not self.guardian.looks_strategic(text) or len(text) < 20:
            return None
        window, items, materials, style = self._participant_context(project_id, text)
        c = self.participant.consider(window, items, materials, style=style)
        if c is None or not c.should_contribute:
            return None
        if c.relevance < self.settings.participation_threshold or not c.text.strip():
            return None
        self.storage.set_last_participation(project_id, message_id)
        return c.text

    def respond_mention(self, project_id, message_id, text):
        if self.participant is None:
            return None
        window, items, materials, style = self._participant_context(project_id, text)
        return self.participant.respond(window, items, materials, text, style=style)
```

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/test_orchestrator.py -v` — PASS; `pytest -q` (expect 112 passed).

- [ ] **Step 5: Commit**

```bash
git add src/concierge/orchestrator.py tests/test_orchestrator.py
git commit -m "feat: orchestrator proactive participation and mention response"
```

---

### Task 5: Bot wiring, mention detection, main, docs

**Files:**
- Modify: `src/concierge/bot.py`, `src/concierge/main.py`
- Modify: `tests/test_bot.py`
- Modify: `README.md`, `SETUP.md`

**Interfaces:**
- Consumes: `Orchestrator.participate/respond_mention` (Task 4).
- Produces:
  - `_is_mention(text: str, bot_username: str | None, reply_to_is_bot: bool) -> bool` — True when `reply_to_is_bot` or when `bot_username` non-empty and `f"@{bot_username.lower()}"` occurs in `text.lower()`.
  - `on_message` new order: ingest → if mention: `respond_mention` reply (skip guardian and participate) → else `check_coherence` (reply if alert) → else `participate` (reply if contribution) → `should_sync`/`run_sync` (always, as today).
  - `main.py` builds `Participant(llm)` and passes `participant=participant` to the Orchestrator.

- [ ] **Step 1: Write the failing test** — append to `tests/test_bot.py`:

```python
def test_is_mention_detection():
    assert bot._is_mention("valeu @meu_bot, o que acha?", "meu_bot", False) is True
    assert bot._is_mention("valeu @Meu_Bot!", "meu_bot", False) is True
    assert bot._is_mention("qualquer texto", "meu_bot", True) is True
    assert bot._is_mention("sem mencao aqui", "meu_bot", False) is False
    assert bot._is_mention("@outro_bot oi", "meu_bot", False) is False
    assert bot._is_mention("@meu_bot oi", None, False) is False
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_bot.py -v -k is_mention`
Expected: FAIL with `AttributeError: module 'concierge.bot' has no attribute '_is_mention'`

- [ ] **Step 3: Implement** — in `src/concierge/bot.py`:

3a. Pure helper (near `_styled`):

```python
def _is_mention(text, bot_username, reply_to_is_bot):
    if reply_to_is_bot:
        return True
    if not bot_username:
        return False
    return f"@{bot_username.lower()}" in (text or "").lower()
```

3b. Replace the `on_message` closure body (inside `build_application`):

```python
    async def on_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        chat = update.effective_chat
        msg = update.message
        user = msg.from_user
        author = (user.username or user.first_name) if user else "unknown"
        pid = orchestrator.ingest_message(
            chat.id, chat.title or str(chat.id), msg.message_id,
            author, msg.text, msg.date.timestamp(),
        )
        reply_to_is_bot = bool(
            msg.reply_to_message
            and msg.reply_to_message.from_user
            and msg.reply_to_message.from_user.id == ctx.bot.id
        )
        if _is_mention(msg.text, ctx.bot.username, reply_to_is_bot):
            reply = orchestrator.respond_mention(pid, msg.message_id, msg.text)
            if reply:
                await msg.reply_text(reply)
        else:
            alert = orchestrator.check_coherence(pid, msg.message_id, msg.text)
            if alert:
                await msg.reply_text(alert)
            else:
                contribution = orchestrator.participate(pid, msg.message_id, msg.text)
                if contribution:
                    await msg.reply_text(contribution)
        if orchestrator.should_sync(pid):
            orchestrator.run_sync(pid)
```

3c. `main.py` — import and wire:

```python
from concierge.participant import Participant
```

and in the Orchestrator construction add `participant=Participant(llm),` after `reconciler=Reconciler(llm),`.

- [ ] **Step 4: Run to verify pass + smoke**

Run: `pytest tests/test_bot.py -v` then `pytest -q` (expect 113 passed).
Run: `PYTHONPATH=src python -c "from concierge.bot import _is_mention, build_application; import concierge.main; print('ok')"` — expect `ok`.

- [ ] **Step 5: Update docs**

`README.md` — after the Commands list, add:

```markdown
## Participation

Mention the bot (`@your_bot`) or reply to one of its messages and it answers
as a team member, drawing on the conversation, the strategic base, and the
uploaded materials. It also makes rare spontaneous contributions (connections,
material knowledge, questions, synthesis) gated by relevance and a cooldown —
tune with `PARTICIPATION_ENABLED`, `PARTICIPATION_COOLDOWN`,
`PARTICIPATION_THRESHOLD`.
```

`SETUP.md` — add to the tuning-knobs table:

```
| `PARTICIPATION_ENABLED` | `true` | Participação espontânea do bot na conversa | `false` desliga |
| `PARTICIPATION_COOLDOWN` | 10 | Mensagens mínimas entre contribuições espontâneas | Baixe para 3 na demo |
| `PARTICIPATION_THRESHOLD` | 0.75 | Relevância mínima para o bot contribuir | Baixe para ~0.6 se quiser mais participação |
```

- [ ] **Step 6: Commit**

```bash
git add src/concierge/bot.py src/concierge/main.py tests/test_bot.py README.md SETUP.md
git commit -m "feat: mention responses and gated spontaneous participation in chat"
```

---

## Self-Review

**Spec coverage:** §1 dois caminhos + portões → T4 (gates) + T5 (mention/order); §2 kinds → T1 (enum) + T3 (prompt); §3.1 participant.py → T3; §3.2 storage → T2, routing → T3, config → T1, orchestrator → T4, bot/main → T5; §4 erros (silêncio) → T3/T4 tests; §5 custo → gates em T4 provam 0-LLM nos portões; §6 testes → embutidos. ✓

**Conscious deviation:** the spec's "menção sem /start responde NOT_STARTED" is unreachable — `on_message` calls `ingest_message`, which auto-creates the project (documented, intentional pre-existing behavior). No dead branch added (YAGNI).

**Placeholders:** none. **Type consistency:** `participate(project_id, message_id, text)`, `respond_mention(...)`, `consider(window, items, materials, style="")`, `respond(window, items, materials, mention_text, style="")`, `_is_mention(text, bot_username, reply_to_is_bot)` consistent across T3–T5; `Contribution` fields match T1; storage methods match T2. Guardian-priority order encoded in T5's on_message. ✓
