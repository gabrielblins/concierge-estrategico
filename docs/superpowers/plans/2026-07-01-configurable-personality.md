# Configurable Personality Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `/personality` lets each group set the bot's voice (presets or free text); guardian alerts come out in that voice via prompt injection (zero extra cost) and command replies are restyled by a `Stylist` (one light LLM call, fail-safe to plain text).

**Architecture:** A `personality` column on `projects` holds the style instruction. `Guardian.check` gains a `style` kwarg injected into its SYSTEM prompt so the alert's `reason` is born in-voice. A new `stylist.py` owns the presets and a `restyle(text, personality)` that returns the original text on empty personality (no LLM call) or on any LLM failure. Bot layer: pure `handle_personality` + a `_styled` helper applied to `/status`, `/sync`, `/why` replies and the `/start` consent notice — never to `/forget`, gates, or canvas data.

**Tech Stack:** Python 3.14, existing LLMClient/call_validated, Pydantic, SQLite.

## Global Constraints

- Personality applies ONLY to conversational surfaces (guardian alert reason, command replies listed above). Canvas blocks, strategic items, and the guardian's JUDGMENT (contradicts/confidence) stay neutral and unaffected.
- `Stylist.restyle`: empty personality → return text unchanged WITHOUT any LLM call; LLM failure/invalid → return original text (never break a command).
- Preset names exactly: `mentor`, `coach`, `zen`, `formal`. `reset` clears. Free text capped at 300 chars (truncated with a notice).
- All LLM calls via `call_validated`. All business logic testable without network.
- `/personality` requires the `/start` consent gate (existing `NOT_STARTED` pattern).
- Shared venv: `. .venv/bin/activate` at repo root (Python 3.14.3); run tests from repo root. Suite currently at 85 passed.

---

## File Structure

```
src/concierge/
  stylist.py       # NEW: PRESETS, Stylist.restyle
  models.py        # +StyledText schema
  storage.py       # projects.personality column + set/get + migration guard
  guardian.py      # check(..., style="") -> SYSTEM prompt injection
  orchestrator.py  # check_coherence reads personality, passes style
  bot.py           # handle_personality, _styled helper, styled replies, registration
  main.py          # builds Stylist, passes to build_application
tests/
  test_stylist.py  # NEW
  + additions to test_storage / test_guardian / test_orchestrator / test_bot
```

---

### Task 1: Storage — personality per project

**Files:**
- Modify: `src/concierge/storage.py`
- Modify: `tests/test_storage.py`

**Interfaces:**
- Produces: `set_personality(project_id: int, text: str) -> None`; `get_personality(project_id: int) -> str` (returns `''` when unset). Schema: `projects` gains `personality TEXT NOT NULL DEFAULT ''` (+ ALTER TABLE migration guard for existing DBs, same pattern as `knowledge_docs.material_type`).

- [ ] **Step 1: Write the failing test** — append to `tests/test_storage.py`:

```python
def test_personality_roundtrip_and_default(storage):
    pid = storage.get_or_create_project(100, "Acme")
    assert storage.get_personality(pid) == ""
    storage.set_personality(pid, "fale como um mentor direto")
    assert storage.get_personality(pid) == "fale como um mentor direto"
    storage.set_personality(pid, "")
    assert storage.get_personality(pid) == ""
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_storage.py -v -k personality`
Expected: FAIL with `AttributeError: 'Storage' object has no attribute 'get_personality'`

- [ ] **Step 3: Implement** — in `src/concierge/storage.py`:

3a. In the `SCHEMA` string, add to the `projects` table (after `mode`):

```sql
    personality TEXT NOT NULL DEFAULT '',
```

3b. In `init_schema`, add a second migration guard next to the existing one:

```python
        try:
            self.conn.execute(
                "ALTER TABLE projects ADD COLUMN personality TEXT NOT NULL DEFAULT ''"
            )
        except sqlite3.OperationalError:
            pass  # column already exists
```

3c. Append inside `Storage`:

```python
    def set_personality(self, project_id: int, text: str) -> None:
        self.conn.execute(
            "UPDATE projects SET personality = ? WHERE id = ?", (text, project_id)
        )
        self.conn.commit()

    def get_personality(self, project_id: int) -> str:
        cur = self.conn.execute(
            "SELECT personality FROM projects WHERE id = ?", (project_id,)
        )
        row = cur.fetchone()
        return row["personality"] if row else ""
```

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/test_storage.py -v`
Expected: PASS (all)

- [ ] **Step 5: Commit**

```bash
git add src/concierge/storage.py tests/test_storage.py
git commit -m "feat: per-project personality storage with migration guard"
```

---

### Task 2: Stylist module and presets

**Files:**
- Modify: `src/concierge/models.py`
- Create: `src/concierge/stylist.py`
- Create: `tests/test_stylist.py`

**Interfaces:**
- Consumes: `call_validated`, `LLMClient`.
- Produces:
  - `StyledText(BaseModel)` in `models.py` with `text: str`.
  - `PRESETS: dict[str, str]` in `stylist.py` with keys exactly `mentor`, `coach`, `zen`, `formal` (Portuguese style instructions below).
  - `Stylist(llm)` with `restyle(text: str, personality: str) -> str`: empty/blank personality → return `text` with NO LLM call; `call_validated` returns `None` → return `text`; else return `result.text`.

- [ ] **Step 1: Write the failing test** — create `tests/test_stylist.py`:

```python
from concierge.stylist import Stylist, PRESETS


def test_presets_have_expected_names():
    assert set(PRESETS) == {"mentor", "coach", "zen", "formal"}
    assert all(isinstance(v, str) and v for v in PRESETS.values())


def test_restyle_empty_personality_skips_llm(fake_llm):
    llm = fake_llm(responses=[])
    s = Stylist(llm)
    assert s.restyle("Canvas atualizado.", "") == "Canvas atualizado."
    assert s.restyle("Canvas atualizado.", "   ") == "Canvas atualizado."
    assert llm.calls == []


def test_restyle_rewrites_in_voice(fake_llm):
    llm = fake_llm(responses=[{"text": "Aí sim! Canvas atualizado, time! 🚀"}])
    s = Stylist(llm)
    out = s.restyle("Canvas atualizado.", PRESETS["coach"])
    assert out == "Aí sim! Canvas atualizado, time! 🚀"
    # prompt carries both the personality and the original text
    assert PRESETS["coach"] in llm.calls[0][0] or PRESETS["coach"] in llm.calls[0][1]
    assert "Canvas atualizado." in llm.calls[0][1]


def test_restyle_falls_back_on_llm_failure(fake_llm):
    llm = fake_llm(responses=[{"bad": 1}, {"bad": 1}])
    s = Stylist(llm)
    assert s.restyle("Canvas atualizado.", "voz qualquer") == "Canvas atualizado."
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_stylist.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'concierge.stylist'`

- [ ] **Step 3: Implement**

3a. Append to `src/concierge/models.py`:

```python
class StyledText(BaseModel):
    text: str
```

3b. Create `src/concierge/stylist.py`:

```python
from concierge.llm.client import call_validated
from concierge.models import StyledText

PRESETS = {
    "mentor": (
        "Fale como um mentor direto e experiente: sem rodeios, aponte o risco "
        "e sugira o próximo passo concreto."
    ),
    "coach": (
        "Fale como um coach motivacional: energético, celebre o progresso "
        "antes de apontar desvios."
    ),
    "zen": (
        "Fale como um conselheiro zen: calmo, socrático — prefira perguntas "
        "que levem a equipe a enxergar o problema."
    ),
    "formal": (
        "Fale como um consultor formal: analítico, impessoal, tom de "
        "relatório executivo."
    ),
}

SYSTEM = (
    "You rewrite short bot messages in a given voice. Keep ALL factual "
    "content intact — numbers, names, block names, commands like /status — "
    "change only the tone. Answer in the same language as the message. "
    "Return JSON {\"text\": rewritten message}."
)


class Stylist:
    def __init__(self, llm):
        self.llm = llm

    def restyle(self, text: str, personality: str) -> str:
        if not personality or not personality.strip():
            return text
        user = f"VOICE:\n{personality}\n\nMESSAGE:\n{text}"
        result = call_validated(self.llm, SYSTEM, user, StyledText)
        if result is None:
            return text
        return result.text
```

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/test_stylist.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add src/concierge/models.py src/concierge/stylist.py tests/test_stylist.py
git commit -m "feat: stylist with presets and fail-safe restyle"
```

---

### Task 3: Guardian voice injection + orchestrator pass-through

**Files:**
- Modify: `src/concierge/guardian.py`
- Modify: `src/concierge/orchestrator.py`
- Modify: `tests/test_guardian.py`, `tests/test_orchestrator.py`

**Interfaces:**
- Consumes: `Storage.get_personality` (Task 1).
- Produces: `Guardian.check(text, known_items, method_context="", style="")` — when `style` non-empty, the SYSTEM prompt sent to the LLM gains the suffix `" Write the 'reason' field in this voice: {style}"`. Empty style → SYSTEM identical to today. `Orchestrator.check_coherence` reads `get_personality(project_id)` and passes it as `style`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_guardian.py`:

```python
def test_check_injects_style_into_system_prompt(fake_llm):
    llm = fake_llm(responses=[{
        "contradicts": False, "item_content": None, "reason": "ok", "confidence": 0.1,
    }])
    g = Guardian(llm)
    g.check("vamos mudar o foco", [], style="fale como um pirata")
    system_sent = llm.calls[0][0]
    assert "fale como um pirata" in system_sent
    assert "Write the 'reason' field in this voice" in system_sent


def test_check_without_style_keeps_prompt_clean(fake_llm):
    llm = fake_llm(responses=[{
        "contradicts": False, "item_content": None, "reason": "ok", "confidence": 0.1,
    }])
    g = Guardian(llm)
    g.check("vamos mudar o foco", [])
    assert "voice" not in llm.calls[0][0].lower()
```

Append to `tests/test_orchestrator.py`:

```python
def test_check_coherence_passes_personality_as_style(fake_llm):
    guardian_llm = fake_llm(responses=[{
        "contradicts": False, "item_content": None, "reason": "ok", "confidence": 0.1,
    }])
    o = _orch_with_guardian(guardian_llm)
    pid = o.storage.get_or_create_project(100, "Acme")
    o.storage.set_personality(pid, "fale como um mentor direto")
    o.check_coherence(pid, 1, "vamos priorizar enterprise")
    assert "fale como um mentor direto" in guardian_llm.calls[0][0]
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_guardian.py tests/test_orchestrator.py -v -k style`
Expected: FAIL with `TypeError: check() got an unexpected keyword argument 'style'` (guardian) and assertion failure (orchestrator).

- [ ] **Step 3: Implement**

`guardian.py` — `check` becomes:

```python
    def check(self, text, known_items, method_context="", style=""):
        items_txt = "\n".join(f"[{i['type']}] {i['content']}" for i in known_items)
        user = (
            f"NEW MESSAGE:\n{text}\n\n"
            f"KNOWN ITEMS:\n{items_txt}\n\n"
            f"METHOD CONTEXT:\n{method_context}"
        )
        system = SYSTEM
        if style:
            system += f" Write the 'reason' field in this voice: {style}"
        return call_validated(self.llm, system, user, CoherenceVerdict)
```

`orchestrator.py` — in `check_coherence`, change the `guardian.check` call to:

```python
        style = self.storage.get_personality(project_id)
        verdict = self.guardian.check(text, known, context, style=style)
```

(The two lines replace the current `verdict = self.guardian.check(text, known, context)`.)

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/test_guardian.py tests/test_orchestrator.py -v`
Expected: PASS (all — existing tests unaffected: default style is empty).

- [ ] **Step 5: Commit**

```bash
git add src/concierge/guardian.py src/concierge/orchestrator.py tests/test_guardian.py tests/test_orchestrator.py
git commit -m "feat: guardian alerts carry the project voice via prompt injection"
```

---

### Task 4: /personality command, styled replies, wiring, docs

**Files:**
- Modify: `src/concierge/bot.py`, `src/concierge/main.py`
- Modify: `tests/test_bot.py`
- Modify: `README.md`, `SETUP.md` (command tables)

**Interfaces:**
- Consumes: `Stylist`, `PRESETS` (Task 2), `set_personality/get_personality` (Task 1).
- Produces:
  - `handle_personality(orchestrator, stylist, chat_id, args: str) -> str` — gate `/start`; empty args → current style (or "nenhuma definida") + preset list + free-text example; `reset` (case-insensitive) → clears and confirms; preset name (case-insensitive) → stores `PRESETS[name]` and confirms via `stylist.restyle` when stylist given; other text → free instruction, truncated at 300 chars (with `"(instrução truncada em 300 caracteres)"` appended to the reply when truncated), stored, confirmed via restyle.
  - `_styled(orchestrator, stylist, chat_id, text) -> str` — returns `text` when `stylist is None` or no project or empty personality; else `stylist.restyle(text, personality)`.
  - `build_application(orchestrator, token, material_service=None, stylist=None)` — the `start`, `status`, `why`, `sync` async closures wrap their reply in `_styled(...)`; `forget`, gates, upload/materials replies stay plain. New `CommandHandler("personality", personality)`.
  - `main.py` builds `Stylist(llm)` and passes it.

- [ ] **Step 1: Write the failing tests** — append to `tests/test_bot.py`:

```python
class _FakeStylist:
    def __init__(self):
        self.calls = []

    def restyle(self, text, personality):
        self.calls.append((text, personality))
        return f"[styled:{personality[:10]}] {text}"


def test_handle_personality_lists_presets_when_no_args(fake_llm):
    o = _orch(fake_llm)
    o.storage.get_or_create_project(100, "Acme")
    reply = bot.handle_personality(o, None, 100, "")
    assert "mentor" in reply and "coach" in reply and "zen" in reply and "formal" in reply
    assert "nenhuma" in reply.lower()


def test_handle_personality_requires_start(fake_llm):
    o = _orch(fake_llm)
    assert bot.handle_personality(o, None, 777, "mentor") == bot.NOT_STARTED


def test_handle_personality_applies_preset_and_persists(fake_llm):
    from concierge.stylist import PRESETS
    o = _orch(fake_llm)
    pid = o.storage.get_or_create_project(100, "Acme")
    st = _FakeStylist()
    reply = bot.handle_personality(o, st, 100, "Mentor")
    assert o.storage.get_personality(pid) == PRESETS["mentor"]
    assert reply.startswith("[styled:")  # confirmation in the new voice


def test_handle_personality_free_text_and_truncation(fake_llm):
    o = _orch(fake_llm)
    pid = o.storage.get_or_create_project(100, "Acme")
    long_text = "fale como um pirata " * 30  # > 300 chars
    reply = bot.handle_personality(o, None, 100, long_text)
    assert len(o.storage.get_personality(pid)) == 300
    assert "truncada" in reply


def test_handle_personality_reset(fake_llm):
    o = _orch(fake_llm)
    pid = o.storage.get_or_create_project(100, "Acme")
    o.storage.set_personality(pid, "algo")
    reply = bot.handle_personality(o, None, 100, "reset")
    assert o.storage.get_personality(pid) == ""
    assert "removida" in reply.lower() or "limpa" in reply.lower()


def test_styled_helper_passthrough_and_restyle(fake_llm):
    o = _orch(fake_llm)
    pid = o.storage.get_or_create_project(100, "Acme")
    # no stylist -> passthrough
    assert bot._styled(o, None, 100, "oi") == "oi"
    st = _FakeStylist()
    # no personality set -> passthrough, stylist not called
    assert bot._styled(o, st, 100, "oi") == "oi"
    assert st.calls == []
    o.storage.set_personality(pid, "voz de mentor")
    out = bot._styled(o, st, 100, "oi")
    assert out.startswith("[styled:") and st.calls[0] == ("oi", "voz de mentor")
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_bot.py -v -k "personality or styled"`
Expected: FAIL with `AttributeError: module 'concierge.bot' has no attribute 'handle_personality'`

- [ ] **Step 3: Implement** — in `src/concierge/bot.py`:

3a. Import near the top (with the other concierge imports):

```python
from concierge.stylist import PRESETS
```

3b. Pure handler + helper (after `handle_materials`):

```python
PERSONALITY_HELP = (
    "Estilo atual: {current}\n\n"
    "Presets: " + ", ".join(sorted(PRESETS)) + "\n"
    "Use /personality <preset>, /personality <descrição livre> "
    "ou /personality reset para limpar."
)

MAX_PERSONALITY = 300


def handle_personality(orchestrator, stylist, chat_id, args):
    pid = orchestrator.storage.get_project(chat_id)
    if pid is None:
        return NOT_STARTED
    text = (args or "").strip()
    if not text:
        current = orchestrator.storage.get_personality(pid) or "nenhuma definida"
        return PERSONALITY_HELP.format(current=current)
    if text.lower() == "reset":
        orchestrator.storage.set_personality(pid, "")
        return "🎭 Personalidade removida. Volto ao tom neutro."
    truncated = False
    if text.lower() in PRESETS:
        instruction = PRESETS[text.lower()]
        label = text.lower()
    else:
        instruction = text[:MAX_PERSONALITY]
        truncated = len(text) > MAX_PERSONALITY
        label = "personalizada"
    orchestrator.storage.set_personality(pid, instruction)
    reply = f"🎭 Personalidade definida ({label})! A partir de agora falo assim."
    if stylist is not None:
        reply = stylist.restyle(reply, instruction)
    if truncated:
        reply += "\n(instrução truncada em 300 caracteres)"
    return reply


def _styled(orchestrator, stylist, chat_id, text):
    if stylist is None:
        return text
    pid = orchestrator.storage.get_project(chat_id)
    if pid is None:
        return text
    personality = orchestrator.storage.get_personality(pid)
    if not personality:
        return text
    return stylist.restyle(text, personality)
```

3c. `build_application` gains `stylist=None` and the styled wrapping. New signature:

```python
def build_application(orchestrator, token, material_service=None, stylist=None):
```

Change these four async closures to wrap replies (only these; `forget`, `upload`, `upload_document`, `materials` stay as-is):

```python
    async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        chat = update.effective_chat
        reply = handle_start(orchestrator, chat.id, chat.title or str(chat.id))
        await update.message.reply_text(_styled(orchestrator, stylist, chat.id, reply))

    async def status(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        chat_id = update.effective_chat.id
        reply = handle_status(orchestrator, chat_id)
        await update.message.reply_text(
            _styled(orchestrator, stylist, chat_id, reply), parse_mode="Markdown"
        )

    async def why(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        chat_id = update.effective_chat.id
        reply = handle_why(orchestrator, chat_id)
        await update.message.reply_text(_styled(orchestrator, stylist, chat_id, reply))

    async def sync(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        chat_id = update.effective_chat.id
        reply = handle_sync(orchestrator, chat_id)
        await update.message.reply_text(_styled(orchestrator, stylist, chat_id, reply))
```

Add the personality closure and registration:

```python
    async def personality(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        args = " ".join(ctx.args) if ctx.args else ""
        await update.message.reply_text(
            handle_personality(orchestrator, stylist, update.effective_chat.id, args)
        )
```

```python
    app.add_handler(CommandHandler("personality", personality))
```

3d. `main.py` — import and wire:

```python
from concierge.stylist import Stylist
```

and in `main()`:

```python
    stylist = Stylist(llm)
    app = build_application(orchestrator, settings.telegram_token, material_service, stylist)
```

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/test_bot.py -v` then `pytest -q`
Expected: all PASS.

- [ ] **Step 5: Smoke build**

Run: `PYTHONPATH=src python -c "from concierge.bot import build_application, handle_personality, _styled; import concierge.main; print('ok')"`
Expected: `ok`

- [ ] **Step 6: Update docs** — add to the command tables in `README.md` and `SETUP.md`:

```
| `/personality` | define a voz do bot (presets: mentor, coach, zen, formal — ou descrição livre; `reset` limpa) |
```

- [ ] **Step 7: Commit**

```bash
git add src/concierge/bot.py src/concierge/main.py tests/test_bot.py README.md SETUP.md
git commit -m "feat: /personality command and styled conversational replies"
```

---

## Self-Review

**Spec coverage:** §2 presets → T2; §3 persistence/column → T1; §4.1 guardian injection (zero cost) → T3; §4.2 Stylist + applied surfaces (`/status`, `/sync`, `/why`, `/start` consent; NOT `/forget`/gates) → T2+T4; §5 command behaviors (list/reset/preset/free-text/truncation/gate) → T4; §6 fail-safe + judgment neutrality → T2 (fallback test) + T3 (style only touches SYSTEM text, verdict schema unchanged); §7 tests → embedded; §8 no new deps. ✓

**Placeholders:** none — complete code in every step. ✓

**Type consistency:** `handle_personality(orchestrator, stylist, chat_id, args)` and `_styled(orchestrator, stylist, chat_id, text)` used consistently in T4 tests and glue; `Stylist.restyle(text, personality)` matches T2; `check(..., style="")` matches T3's orchestrator call `guardian.check(text, known, context, style=style)`. `PRESETS` keys lowercase; handler lowercases input before lookup. ✓

**Note:** `PERSONALITY_HELP` builds the preset list at import time from `PRESETS` (single source of truth, no drift).
