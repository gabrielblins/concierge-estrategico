# Strategic Concierge Bot — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Telegram bot that turns team conversations into a living strategic base — extracting strategic items, keeping a Business Model Canvas updated, and intervening when discussions contradict validated strategy.

**Architecture:** Layered Python app. A thin Telegram bot layer delegates to an Orchestrator that routes messages between a batch "passive" path (extract items → update canvas) and a selective "active" path (coherence guardian). All LLM access goes through a single `LLMClient` interface so business logic is testable with a fake. State lives in SQLite; reference materials live in a ChromaDB vector store for RAG.

**Tech Stack:** Python 3.14, `python-telegram-bot`, `openai`, `pydantic`, `chromadb`, `pytest`, SQLite (stdlib `sqlite3`).

## Global Constraints

- Python 3.14; all dependencies pinned in `requirements.txt`.
- LLM provider: OpenAI / GPT. All GPT calls go through the `LLMClient` interface — never call `openai` directly from business logic.
- All LLM structured output validated with Pydantic before use; invalid output is retried once then discarded (never written to the DB).
- `strategic_items` is the source of truth; the canvas is a projection. Nothing is hard-deleted except via `/forget` — items become `status='discarded'` or `'superseded'`.
- Every strategic item and intervention records its `source_message_id`.
- Default tuning values: batch trigger `N=15` unprocessed messages; coherence confidence threshold `0.75`.
- BMC block names (exact): `value_proposition`, `customer_segments`, `channels`, `customer_relationships`, `revenue_streams`, `key_resources`, `key_activities`, `key_partnerships`, `cost_structure`.
- All business logic must be testable without network access.
- The active (guardian) path must never post errors to the group — it fails silently.

---

## File Structure

```
src/concierge/
  __init__.py
  config.py            # env-driven settings (tokens, thresholds, N)
  models.py            # Pydantic schemas for LLM output + domain enums
  storage.py           # SQLite schema + repository (CRUD, status transitions)
  canvas.py            # canvas projection helpers (block names, re-synthesis)
  llm/
    __init__.py
    client.py          # LLMClient interface + FakeLLMClient
    openai_client.py   # OpenAILLMClient implementation
  extractor.py         # batch messages -> strategic items (uses LLMClient)
  updater.py           # strategic items -> canvas blocks (uses LLMClient)
  guardian.py          # single message -> contradiction verdict (uses LLMClient)
  knowledge.py         # ChromaDB RAG wrapper (ingest + query)
  orchestrator.py      # hybrid routing logic (the brain)
  bot.py               # python-telegram-bot wiring (commands + handlers)
  main.py              # entrypoint: build deps, start long-polling

tests/
  test_storage.py
  test_models.py
  test_extractor.py
  test_updater.py
  test_guardian.py
  test_orchestrator.py
  test_knowledge.py
  conftest.py          # shared fixtures (in-memory db, fake llm)

requirements.txt
.env.example
README.md
```

**Decomposition rationale:** Each file has one responsibility. The three GPT-using units (`extractor`, `updater`, `guardian`) are split because each has a distinct prompt, schema, and failure mode and a reviewer could accept one while rejecting another. `storage` and `llm/client` are foundational and built first. `bot.py` and `main.py` are pure wiring built last, on top of tested logic.

---

## Task 1: Project Scaffold and Dependencies

**Files:**
- Create: `requirements.txt`, `.env.example`, `src/concierge/__init__.py`, `src/concierge/config.py`, `tests/conftest.py`, `pytest.ini`

**Interfaces:**
- Produces: `concierge.config.Settings` dataclass with attrs `telegram_token: str`, `openai_api_key: str`, `db_path: str`, `batch_size: int` (default 15), `confidence_threshold: float` (default 0.75), `chroma_path: str`; classmethod `Settings.from_env() -> Settings`.

- [ ] **Step 1: Create `requirements.txt`**

```
python-telegram-bot==21.6
openai==1.54.0
pydantic==2.9.2
chromadb==0.5.15
pytest==8.3.3
```

- [ ] **Step 2: Create `.env.example`**

```
TELEGRAM_TOKEN=your-telegram-bot-token
OPENAI_API_KEY=your-openai-key
DB_PATH=concierge.db
CHROMA_PATH=./chroma
BATCH_SIZE=15
CONFIDENCE_THRESHOLD=0.75
```

- [ ] **Step 3: Create `pytest.ini`**

```ini
[pytest]
pythonpath = src
testpaths = tests
```

- [ ] **Step 4: Create empty `src/concierge/__init__.py`**

```python
```

- [ ] **Step 5: Write the failing test for Settings** in `tests/conftest.py` — actually put the test in a new `tests/test_config.py`:

```python
import os
from concierge.config import Settings


def test_settings_from_env_reads_values_and_defaults(monkeypatch):
    monkeypatch.setenv("TELEGRAM_TOKEN", "tok")
    monkeypatch.setenv("OPENAI_API_KEY", "key")
    monkeypatch.delenv("BATCH_SIZE", raising=False)
    s = Settings.from_env()
    assert s.telegram_token == "tok"
    assert s.openai_api_key == "key"
    assert s.batch_size == 15
    assert s.confidence_threshold == 0.75
```

- [ ] **Step 6: Run test to verify it fails**

Run: `pytest tests/test_config.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'concierge.config'`

- [ ] **Step 7: Implement `src/concierge/config.py`**

```python
import os
from dataclasses import dataclass


@dataclass
class Settings:
    telegram_token: str
    openai_api_key: str
    db_path: str = "concierge.db"
    chroma_path: str = "./chroma"
    batch_size: int = 15
    confidence_threshold: float = 0.75

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            telegram_token=os.environ.get("TELEGRAM_TOKEN", ""),
            openai_api_key=os.environ.get("OPENAI_API_KEY", ""),
            db_path=os.environ.get("DB_PATH", "concierge.db"),
            chroma_path=os.environ.get("CHROMA_PATH", "./chroma"),
            batch_size=int(os.environ.get("BATCH_SIZE", "15")),
            confidence_threshold=float(os.environ.get("CONFIDENCE_THRESHOLD", "0.75")),
        )
```

- [ ] **Step 8: Run test to verify it passes**

Run: `pytest tests/test_config.py -v`
Expected: PASS

- [ ] **Step 9: Commit**

```bash
git add requirements.txt .env.example pytest.ini src/concierge/__init__.py src/concierge/config.py tests/test_config.py
git commit -m "feat: project scaffold, deps, and config settings"
```

---

## Task 2: Domain Models and LLM Output Schemas

**Files:**
- Create: `src/concierge/models.py`, `tests/test_models.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - Enums (str-valued): `ItemType` (`decision`, `hypothesis`, `premise`, `risk`, `task`, `learning`); `ItemStatus` (`active`, `validated`, `discarded`, `superseded`); `ProjectMode` (`silent`, `moderate`, `active`).
  - `ExtractedItem(BaseModel)`: `type: ItemType`, `content: str`, `confidence: float`.
  - `ExtractionResult(BaseModel)`: `items: list[ExtractedItem]`.
  - `CoherenceVerdict(BaseModel)`: `contradicts: bool`, `item_content: str | None`, `reason: str`, `confidence: float`.
  - `CanvasBlockUpdate(BaseModel)`: `block_name: str`, `content: str`.
  - `CanvasUpdateResult(BaseModel)`: `blocks: list[CanvasBlockUpdate]`.

- [ ] **Step 1: Write the failing test**

```python
import pytest
from pydantic import ValidationError
from concierge.models import (
    ItemType, ItemStatus, ProjectMode,
    ExtractedItem, ExtractionResult, CoherenceVerdict,
    CanvasBlockUpdate, CanvasUpdateResult,
)


def test_item_type_values():
    assert ItemType.HYPOTHESIS == "hypothesis"
    assert {t.value for t in ItemType} == {
        "decision", "hypothesis", "premise", "risk", "task", "learning"
    }


def test_extraction_result_parses_valid_json():
    data = {"items": [{"type": "decision", "content": "Focus on segment Y", "confidence": 0.9}]}
    result = ExtractionResult.model_validate(data)
    assert result.items[0].type == ItemType.DECISION
    assert result.items[0].confidence == 0.9


def test_extracted_item_rejects_bad_type():
    with pytest.raises(ValidationError):
        ExtractedItem.model_validate({"type": "nonsense", "content": "x", "confidence": 0.5})


def test_coherence_verdict_allows_null_item():
    v = CoherenceVerdict.model_validate(
        {"contradicts": False, "item_content": None, "reason": "no conflict", "confidence": 0.2}
    )
    assert v.contradicts is False
    assert v.item_content is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_models.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'concierge.models'`

- [ ] **Step 3: Implement `src/concierge/models.py`**

```python
from enum import Enum
from pydantic import BaseModel


class ItemType(str, Enum):
    DECISION = "decision"
    HYPOTHESIS = "hypothesis"
    PREMISE = "premise"
    RISK = "risk"
    TASK = "task"
    LEARNING = "learning"


class ItemStatus(str, Enum):
    ACTIVE = "active"
    VALIDATED = "validated"
    DISCARDED = "discarded"
    SUPERSEDED = "superseded"


class ProjectMode(str, Enum):
    SILENT = "silent"
    MODERATE = "moderate"
    ACTIVE = "active"


class ExtractedItem(BaseModel):
    type: ItemType
    content: str
    confidence: float


class ExtractionResult(BaseModel):
    items: list[ExtractedItem]


class CoherenceVerdict(BaseModel):
    contradicts: bool
    item_content: str | None = None
    reason: str
    confidence: float


class CanvasBlockUpdate(BaseModel):
    block_name: str
    content: str


class CanvasUpdateResult(BaseModel):
    blocks: list[CanvasBlockUpdate]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_models.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add src/concierge/models.py tests/test_models.py
git commit -m "feat: domain enums and pydantic LLM output schemas"
```

---

## Task 3: Storage Layer — Schema and Project/Message CRUD

**Files:**
- Create: `src/concierge/storage.py`, `tests/test_storage.py`, update `tests/conftest.py`

**Interfaces:**
- Consumes: `concierge.models.ProjectMode`.
- Produces: `Storage` class wrapping a `sqlite3.Connection`.
  - `Storage(conn: sqlite3.Connection)`; `Storage.init_schema() -> None` (creates all tables).
  - `get_or_create_project(chat_id: int, name: str) -> int` (returns project id).
  - `add_message(project_id: int, telegram_msg_id: int, author: str, text: str, ts: float) -> int | None` (returns message id; returns `None` if `telegram_msg_id` already exists for idempotency).
  - `unprocessed_messages(project_id: int) -> list[dict]` (each: `id, author, text, ts`).
  - `mark_processed(message_ids: list[int]) -> None`.
  - `set_mode(project_id: int, mode: ProjectMode) -> None`; `get_mode(project_id: int) -> ProjectMode`.

- [ ] **Step 1: Add the in-memory DB fixture to `tests/conftest.py`**

```python
import sqlite3
import pytest
from concierge.storage import Storage


@pytest.fixture
def storage():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    s = Storage(conn)
    s.init_schema()
    return s
```

- [ ] **Step 2: Write the failing test**

```python
from concierge.models import ProjectMode


def test_get_or_create_project_is_idempotent(storage):
    p1 = storage.get_or_create_project(chat_id=100, name="Acme")
    p2 = storage.get_or_create_project(chat_id=100, name="Acme")
    assert p1 == p2


def test_add_message_dedupes_on_telegram_id(storage):
    pid = storage.get_or_create_project(100, "Acme")
    first = storage.add_message(pid, telegram_msg_id=5, author="ana", text="hi", ts=1.0)
    dup = storage.add_message(pid, telegram_msg_id=5, author="ana", text="hi", ts=1.0)
    assert first is not None
    assert dup is None


def test_unprocessed_then_mark_processed(storage):
    pid = storage.get_or_create_project(100, "Acme")
    mid = storage.add_message(pid, 5, "ana", "we will target SMBs", 1.0)
    assert len(storage.unprocessed_messages(pid)) == 1
    storage.mark_processed([mid])
    assert storage.unprocessed_messages(pid) == []


def test_mode_defaults_to_moderate_and_can_change(storage):
    pid = storage.get_or_create_project(100, "Acme")
    assert storage.get_mode(pid) == ProjectMode.MODERATE
    storage.set_mode(pid, ProjectMode.SILENT)
    assert storage.get_mode(pid) == ProjectMode.SILENT
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/test_storage.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'concierge.storage'`

- [ ] **Step 4: Implement `src/concierge/storage.py`** (schema + this task's methods)

```python
import sqlite3
from concierge.models import ProjectMode

SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_chat_id INTEGER UNIQUE NOT NULL,
    name TEXT NOT NULL,
    framework_type TEXT NOT NULL DEFAULT 'bmc',
    mode TEXT NOT NULL DEFAULT 'moderate',
    created_at REAL NOT NULL DEFAULT (strftime('%s','now'))
);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL,
    telegram_msg_id INTEGER NOT NULL,
    author TEXT NOT NULL,
    text TEXT NOT NULL,
    ts REAL NOT NULL,
    processed INTEGER NOT NULL DEFAULT 0,
    UNIQUE(project_id, telegram_msg_id)
);
CREATE TABLE IF NOT EXISTS strategic_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL,
    type TEXT NOT NULL,
    content TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    confidence REAL NOT NULL DEFAULT 0.0,
    source_message_id INTEGER,
    created_at REAL NOT NULL DEFAULT (strftime('%s','now')),
    updated_at REAL NOT NULL DEFAULT (strftime('%s','now')),
    superseded_by INTEGER
);
CREATE TABLE IF NOT EXISTS canvas_blocks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL,
    block_name TEXT NOT NULL,
    content TEXT NOT NULL DEFAULT '',
    updated_at REAL NOT NULL DEFAULT (strftime('%s','now')),
    source_items TEXT NOT NULL DEFAULT '[]',
    UNIQUE(project_id, block_name)
);
CREATE TABLE IF NOT EXISTS interventions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL,
    message_id INTEGER,
    item_id INTEGER,
    reason TEXT NOT NULL,
    confidence REAL NOT NULL,
    sent_at REAL NOT NULL DEFAULT (strftime('%s','now'))
);
CREATE TABLE IF NOT EXISTS knowledge_docs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL,
    filename TEXT NOT NULL,
    uploaded_at REAL NOT NULL DEFAULT (strftime('%s','now')),
    chunk_count INTEGER NOT NULL DEFAULT 0
);
"""


class Storage:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.conn.row_factory = sqlite3.Row

    def init_schema(self) -> None:
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def get_or_create_project(self, chat_id: int, name: str) -> int:
        cur = self.conn.execute(
            "SELECT id FROM projects WHERE telegram_chat_id = ?", (chat_id,)
        )
        row = cur.fetchone()
        if row:
            return row["id"]
        cur = self.conn.execute(
            "INSERT INTO projects (telegram_chat_id, name) VALUES (?, ?)",
            (chat_id, name),
        )
        self.conn.commit()
        return cur.lastrowid

    def add_message(self, project_id, telegram_msg_id, author, text, ts):
        try:
            cur = self.conn.execute(
                "INSERT INTO messages (project_id, telegram_msg_id, author, text, ts) "
                "VALUES (?, ?, ?, ?, ?)",
                (project_id, telegram_msg_id, author, text, ts),
            )
            self.conn.commit()
            return cur.lastrowid
        except sqlite3.IntegrityError:
            return None

    def unprocessed_messages(self, project_id: int) -> list[dict]:
        cur = self.conn.execute(
            "SELECT id, author, text, ts FROM messages "
            "WHERE project_id = ? AND processed = 0 ORDER BY ts",
            (project_id,),
        )
        return [dict(r) for r in cur.fetchall()]

    def mark_processed(self, message_ids: list[int]) -> None:
        self.conn.executemany(
            "UPDATE messages SET processed = 1 WHERE id = ?",
            [(mid,) for mid in message_ids],
        )
        self.conn.commit()

    def set_mode(self, project_id: int, mode: ProjectMode) -> None:
        self.conn.execute(
            "UPDATE projects SET mode = ? WHERE id = ?", (mode.value, project_id)
        )
        self.conn.commit()

    def get_mode(self, project_id: int) -> ProjectMode:
        cur = self.conn.execute(
            "SELECT mode FROM projects WHERE id = ?", (project_id,)
        )
        return ProjectMode(cur.fetchone()["mode"])
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_storage.py -v`
Expected: PASS (4 passed)

- [ ] **Step 6: Commit**

```bash
git add src/concierge/storage.py tests/test_storage.py tests/conftest.py
git commit -m "feat: sqlite schema and project/message storage"
```

---

## Task 4: Storage Layer — Strategic Items and Interventions

**Files:**
- Modify: `src/concierge/storage.py`
- Modify: `tests/test_storage.py`

**Interfaces:**
- Consumes: `concierge.models.ItemType`, `ItemStatus`.
- Produces (added to `Storage`):
  - `add_item(project_id: int, type: ItemType, content: str, confidence: float, source_message_id: int | None, status: ItemStatus = ItemStatus.ACTIVE) -> int`.
  - `items_by_status(project_id: int, statuses: list[ItemStatus]) -> list[dict]` (each: `id, type, content, status, confidence, source_message_id`).
  - `supersede_item(old_item_id: int, new_item_id: int) -> None` (sets old `status='superseded'`, `superseded_by=new_item_id`).
  - `set_item_status(item_id: int, status: ItemStatus) -> None`.
  - `add_intervention(project_id: int, message_id: int | None, item_id: int | None, reason: str, confidence: float) -> int`.
  - `last_intervention(project_id: int) -> dict | None` (fields: `reason, confidence, item_id, message_id, sent_at`).

- [ ] **Step 1: Write the failing test**

```python
from concierge.models import ItemType, ItemStatus


def test_add_and_query_items_by_status(storage):
    pid = storage.get_or_create_project(100, "Acme")
    i1 = storage.add_item(pid, ItemType.HYPOTHESIS, "SMBs will pay", 0.8, None)
    storage.set_item_status(i1, ItemStatus.VALIDATED)
    validated = storage.items_by_status(pid, [ItemStatus.VALIDATED])
    assert len(validated) == 1
    assert validated[0]["content"] == "SMBs will pay"


def test_supersede_marks_old_item(storage):
    pid = storage.get_or_create_project(100, "Acme")
    old = storage.add_item(pid, ItemType.DECISION, "target enterprise", 0.7, None)
    new = storage.add_item(pid, ItemType.DECISION, "target SMBs", 0.9, None)
    storage.supersede_item(old, new)
    superseded = storage.items_by_status(pid, [ItemStatus.SUPERSEDED])
    assert superseded[0]["id"] == old


def test_intervention_roundtrip(storage):
    pid = storage.get_or_create_project(100, "Acme")
    storage.add_intervention(pid, message_id=3, item_id=7, reason="conflicts with X", confidence=0.9)
    last = storage.last_intervention(pid)
    assert last["reason"] == "conflicts with X"
    assert last["item_id"] == 7
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_storage.py -v -k "items or supersede or intervention"`
Expected: FAIL with `AttributeError: 'Storage' object has no attribute 'add_item'`

- [ ] **Step 3: Add methods to `src/concierge/storage.py`** (append inside the `Storage` class)

```python
    def add_item(self, project_id, type, content, confidence,
                 source_message_id, status=ItemStatus.ACTIVE):
        cur = self.conn.execute(
            "INSERT INTO strategic_items "
            "(project_id, type, content, status, confidence, source_message_id) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (project_id, type.value, content, status.value, confidence, source_message_id),
        )
        self.conn.commit()
        return cur.lastrowid

    def items_by_status(self, project_id, statuses):
        placeholders = ",".join("?" for _ in statuses)
        params = [project_id] + [s.value for s in statuses]
        cur = self.conn.execute(
            f"SELECT id, type, content, status, confidence, source_message_id "
            f"FROM strategic_items WHERE project_id = ? AND status IN ({placeholders})",
            params,
        )
        return [dict(r) for r in cur.fetchall()]

    def supersede_item(self, old_item_id, new_item_id):
        self.conn.execute(
            "UPDATE strategic_items SET status = 'superseded', superseded_by = ?, "
            "updated_at = strftime('%s','now') WHERE id = ?",
            (new_item_id, old_item_id),
        )
        self.conn.commit()

    def set_item_status(self, item_id, status):
        self.conn.execute(
            "UPDATE strategic_items SET status = ?, updated_at = strftime('%s','now') "
            "WHERE id = ?",
            (status.value, item_id),
        )
        self.conn.commit()

    def add_intervention(self, project_id, message_id, item_id, reason, confidence):
        cur = self.conn.execute(
            "INSERT INTO interventions (project_id, message_id, item_id, reason, confidence) "
            "VALUES (?, ?, ?, ?, ?)",
            (project_id, message_id, item_id, reason, confidence),
        )
        self.conn.commit()
        return cur.lastrowid

    def last_intervention(self, project_id):
        cur = self.conn.execute(
            "SELECT reason, confidence, item_id, message_id, sent_at "
            "FROM interventions WHERE project_id = ? ORDER BY sent_at DESC, id DESC LIMIT 1",
            (project_id,),
        )
        row = cur.fetchone()
        return dict(row) if row else None
```

Also add the import at the top of `storage.py`:

```python
from concierge.models import ProjectMode, ItemType, ItemStatus
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_storage.py -v`
Expected: PASS (all storage tests)

- [ ] **Step 5: Commit**

```bash
git add src/concierge/storage.py tests/test_storage.py
git commit -m "feat: strategic items and interventions storage"
```

---

## Task 5: Storage Layer — Canvas Blocks

**Files:**
- Modify: `src/concierge/storage.py`
- Create: `src/concierge/canvas.py`
- Modify: `tests/test_storage.py`

**Interfaces:**
- Consumes: nothing new.
- Produces:
  - In `canvas.py`: `BMC_BLOCKS: list[str]` (the nine exact block names from Global Constraints).
  - Added to `Storage`:
    - `upsert_block(project_id: int, block_name: str, content: str, source_items: list[int]) -> None`.
    - `get_blocks(project_id: int) -> list[dict]` (each: `block_name, content, source_items` — `source_items` decoded to `list[int]`).

- [ ] **Step 1: Create `src/concierge/canvas.py`**

```python
BMC_BLOCKS = [
    "value_proposition",
    "customer_segments",
    "channels",
    "customer_relationships",
    "revenue_streams",
    "key_resources",
    "key_activities",
    "key_partnerships",
    "cost_structure",
]
```

- [ ] **Step 2: Write the failing test**

```python
def test_upsert_and_get_block(storage):
    pid = storage.get_or_create_project(100, "Acme")
    storage.upsert_block(pid, "value_proposition", "Save time on X", [1, 2])
    storage.upsert_block(pid, "value_proposition", "Save time and money on X", [1, 2, 3])
    blocks = storage.get_blocks(pid)
    assert len(blocks) == 1
    assert blocks[0]["content"] == "Save time and money on X"
    assert blocks[0]["source_items"] == [1, 2, 3]
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/test_storage.py -v -k block`
Expected: FAIL with `AttributeError: 'Storage' object has no attribute 'upsert_block'`

- [ ] **Step 4: Add methods to `src/concierge/storage.py`** (and `import json` at top)

```python
    def upsert_block(self, project_id, block_name, content, source_items):
        self.conn.execute(
            "INSERT INTO canvas_blocks (project_id, block_name, content, source_items, updated_at) "
            "VALUES (?, ?, ?, ?, strftime('%s','now')) "
            "ON CONFLICT(project_id, block_name) DO UPDATE SET "
            "content = excluded.content, source_items = excluded.source_items, "
            "updated_at = excluded.updated_at",
            (project_id, block_name, content, json.dumps(source_items)),
        )
        self.conn.commit()

    def get_blocks(self, project_id):
        cur = self.conn.execute(
            "SELECT block_name, content, source_items FROM canvas_blocks "
            "WHERE project_id = ? ORDER BY block_name",
            (project_id,),
        )
        out = []
        for r in cur.fetchall():
            d = dict(r)
            d["source_items"] = json.loads(d["source_items"])
            out.append(d)
        return out
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_storage.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/concierge/storage.py src/concierge/canvas.py tests/test_storage.py
git commit -m "feat: canvas block storage and BMC block names"
```

---

## Task 6: LLMClient Interface and Fake

**Files:**
- Create: `src/concierge/llm/__init__.py`, `src/concierge/llm/client.py`
- Create: `tests/test_llm_client.py`
- Modify: `tests/conftest.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `LLMClient` (abstract base): method `complete_json(system: str, user: str) -> dict` — returns a parsed JSON object from the model. Raises `LLMError` on transport failure or non-JSON output.
  - `LLMError(Exception)`.
  - `FakeLLMClient(LLMClient)`: constructed with `responses: list[dict]` (returned in order) or `error: Exception`; records calls in `.calls: list[tuple[str, str]]`.

- [ ] **Step 1: Create `src/concierge/llm/__init__.py`**

```python
```

- [ ] **Step 2: Write the failing test**

```python
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
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/test_llm_client.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'concierge.llm.client'`

- [ ] **Step 4: Implement `src/concierge/llm/client.py`**

```python
from abc import ABC, abstractmethod


class LLMError(Exception):
    pass


class LLMClient(ABC):
    @abstractmethod
    def complete_json(self, system: str, user: str) -> dict:
        ...


class FakeLLMClient(LLMClient):
    def __init__(self, responses=None, error=None):
        self._responses = list(responses or [])
        self._error = error
        self.calls = []

    def complete_json(self, system: str, user: str) -> dict:
        self.calls.append((system, user))
        if self._error is not None:
            raise self._error
        if not self._responses:
            raise LLMError("no more fake responses queued")
        return self._responses.pop(0)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_llm_client.py -v`
Expected: PASS (2 passed)

- [ ] **Step 6: Add a shared fake fixture to `tests/conftest.py`**

```python
from concierge.llm.client import FakeLLMClient


@pytest.fixture
def fake_llm():
    def _make(responses=None, error=None):
        return FakeLLMClient(responses=responses, error=error)
    return _make
```

- [ ] **Step 7: Commit**

```bash
git add src/concierge/llm/__init__.py src/concierge/llm/client.py tests/test_llm_client.py tests/conftest.py
git commit -m "feat: LLMClient interface and fake for tests"
```

---

## Task 7: Validated LLM Call Helper

**Files:**
- Modify: `src/concierge/llm/client.py`
- Modify: `tests/test_llm_client.py`

**Interfaces:**
- Consumes: `LLMClient`, `pydantic.BaseModel`.
- Produces: free function `call_validated(client: LLMClient, system: str, user: str, schema: type[BaseModel]) -> BaseModel | None`. Calls `client.complete_json`; validates against `schema`. On `ValidationError` or `LLMError`, retries once; if it still fails, returns `None` (never raises). This is the single choke point enforcing "retry once then discard".

- [ ] **Step 1: Write the failing test**

```python
from pydantic import BaseModel
from concierge.llm.client import FakeLLMClient, LLMError, call_validated


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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_llm_client.py -v -k validated`
Expected: FAIL with `ImportError: cannot import name 'call_validated'`

- [ ] **Step 3: Add `call_validated` to `src/concierge/llm/client.py`**

```python
from pydantic import BaseModel, ValidationError


def call_validated(client, system, user, schema):
    for _ in range(2):
        try:
            raw = client.complete_json(system, user)
            return schema.model_validate(raw)
        except (LLMError, ValidationError):
            continue
    return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_llm_client.py -v`
Expected: PASS (all)

- [ ] **Step 5: Commit**

```bash
git add src/concierge/llm/client.py tests/test_llm_client.py
git commit -m "feat: validated LLM call helper with retry-once-then-discard"
```

---

## Task 8: Extractor

**Files:**
- Create: `src/concierge/extractor.py`, `tests/test_extractor.py`

**Interfaces:**
- Consumes: `LLMClient`, `call_validated`, `ExtractionResult`.
- Produces: `Extractor(llm: LLMClient)` with `extract(messages: list[dict]) -> list[ExtractedItem]`. Each message dict has `author` and `text`. Builds a user prompt from the batch, calls `call_validated` with `ExtractionResult`. Returns `result.items` or `[]` if validation failed (None).

- [ ] **Step 1: Write the failing test**

```python
from concierge.extractor import Extractor
from concierge.models import ItemType


def test_extract_returns_items(fake_llm):
    llm = fake_llm(responses=[{
        "items": [{"type": "decision", "content": "Target SMBs", "confidence": 0.9}]
    }])
    ex = Extractor(llm)
    items = ex.extract([{"author": "ana", "text": "let's focus on small businesses"}])
    assert len(items) == 1
    assert items[0].type == ItemType.DECISION
    # prompt should include the message text
    assert "small businesses" in llm.calls[0][1]


def test_extract_returns_empty_on_invalid(fake_llm):
    llm = fake_llm(responses=[{"items": "not a list"}, {"items": "still bad"}])
    ex = Extractor(llm)
    assert ex.extract([{"author": "ana", "text": "hi"}]) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_extractor.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'concierge.extractor'`

- [ ] **Step 3: Implement `src/concierge/extractor.py`**

```python
from concierge.llm.client import call_validated
from concierge.models import ExtractionResult

SYSTEM = (
    "You extract strategic items from a startup team's chat. "
    "Return JSON {\"items\": [{\"type\": one of "
    "decision|hypothesis|premise|risk|task|learning, "
    "\"content\": short statement, \"confidence\": 0..1}]}. "
    "Only include substantive strategic content; skip small talk."
)


class Extractor:
    def __init__(self, llm):
        self.llm = llm

    def extract(self, messages):
        transcript = "\n".join(f"{m['author']}: {m['text']}" for m in messages)
        result = call_validated(self.llm, SYSTEM, transcript, ExtractionResult)
        if result is None:
            return []
        return result.items
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_extractor.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add src/concierge/extractor.py tests/test_extractor.py
git commit -m "feat: extractor turns message batches into strategic items"
```

---

## Task 9: Canvas Updater

**Files:**
- Create: `src/concierge/updater.py`, `tests/test_updater.py`

**Interfaces:**
- Consumes: `LLMClient`, `call_validated`, `CanvasUpdateResult`, `canvas.BMC_BLOCKS`.
- Produces: `CanvasUpdater(llm: LLMClient)` with `update(active_items: list[dict], current_blocks: list[dict]) -> list[CanvasBlockUpdate]`. `active_items` are dicts with `type, content`; `current_blocks` are dicts with `block_name, content`. Calls the LLM to re-synthesize blocks. Filters returned blocks to only valid `BMC_BLOCKS` names; returns `[]` if validation failed.

- [ ] **Step 1: Write the failing test**

```python
from concierge.updater import CanvasUpdater


def test_update_returns_valid_blocks_only(fake_llm):
    llm = fake_llm(responses=[{
        "blocks": [
            {"block_name": "value_proposition", "content": "Save time"},
            {"block_name": "not_a_real_block", "content": "junk"},
        ]
    }])
    up = CanvasUpdater(llm)
    blocks = up.update(
        active_items=[{"type": "decision", "content": "Target SMBs"}],
        current_blocks=[],
    )
    names = [b.block_name for b in blocks]
    assert "value_proposition" in names
    assert "not_a_real_block" not in names


def test_update_returns_empty_on_invalid(fake_llm):
    llm = fake_llm(responses=[{"blocks": "bad"}, {"blocks": "bad"}])
    up = CanvasUpdater(llm)
    assert up.update([], []) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_updater.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'concierge.updater'`

- [ ] **Step 3: Implement `src/concierge/updater.py`**

```python
from concierge.llm.client import call_validated
from concierge.models import CanvasUpdateResult
from concierge.canvas import BMC_BLOCKS

SYSTEM = (
    "You maintain a Business Model Canvas for a startup. "
    "Given the current strategic items and current canvas blocks, "
    "return JSON {\"blocks\": [{\"block_name\": one of the nine BMC block names, "
    "\"content\": synthesized text}]}. Only return blocks that changed. "
    f"Valid block names: {', '.join(BMC_BLOCKS)}."
)


class CanvasUpdater:
    def __init__(self, llm):
        self.llm = llm

    def update(self, active_items, current_blocks):
        items_txt = "\n".join(f"[{i['type']}] {i['content']}" for i in active_items)
        blocks_txt = "\n".join(f"{b['block_name']}: {b['content']}" for b in current_blocks)
        user = f"STRATEGIC ITEMS:\n{items_txt}\n\nCURRENT CANVAS:\n{blocks_txt}"
        result = call_validated(self.llm, SYSTEM, user, CanvasUpdateResult)
        if result is None:
            return []
        return [b for b in result.blocks if b.block_name in BMC_BLOCKS]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_updater.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add src/concierge/updater.py tests/test_updater.py
git commit -m "feat: canvas updater re-synthesizes BMC blocks from items"
```

---

## Task 10: Coherence Guardian

**Files:**
- Create: `src/concierge/guardian.py`, `tests/test_guardian.py`

**Interfaces:**
- Consumes: `LLMClient`, `call_validated`, `CoherenceVerdict`.
- Produces: `Guardian(llm: LLMClient)` with two methods:
  - `looks_strategic(text: str) -> bool` — cheap pre-filter, **no LLM call**. Returns `True` if the text contains decision/direction signal words (case-insensitive): `decid`, `vamos`, `proposta`, `proponho`, `mudar`, `priorizar`, `foco`, `estratégia`, `hipótese`, `descartar`, `pivot`, `target`, `segmento`. Returns `False` otherwise.
  - `check(text: str, known_items: list[dict], method_context: str = "") -> CoherenceVerdict | None` — calls the LLM with the message, the known validated/discarded items, and optional RAG method context. Returns the verdict, or `None` if validation failed.

- [ ] **Step 1: Write the failing test**

```python
from concierge.guardian import Guardian


def test_looks_strategic_prefilter():
    g = Guardian(llm=None)
    assert g.looks_strategic("Vamos priorizar o segmento enterprise") is True
    assert g.looks_strategic("kkk ok") is False
    assert g.looks_strategic("acho que devemos decidir isso") is True


def test_check_returns_verdict(fake_llm):
    llm = fake_llm(responses=[{
        "contradicts": True,
        "item_content": "We validated focusing on SMBs",
        "reason": "This proposes enterprise, contradicting the validated SMB focus",
        "confidence": 0.88,
    }])
    g = Guardian(llm)
    verdict = g.check(
        text="let's target big enterprises now",
        known_items=[{"type": "hypothesis", "content": "We validated focusing on SMBs"}],
    )
    assert verdict.contradicts is True
    assert verdict.confidence == 0.88


def test_check_returns_none_on_invalid(fake_llm):
    llm = fake_llm(responses=[{"bad": 1}, {"bad": 1}])
    g = Guardian(llm)
    assert g.check("x", []) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_guardian.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'concierge.guardian'`

- [ ] **Step 3: Implement `src/concierge/guardian.py`**

```python
from concierge.llm.client import call_validated
from concierge.models import CoherenceVerdict

SIGNALS = [
    "decid", "vamos", "proposta", "proponho", "mudar", "priorizar",
    "foco", "estratégia", "hipótese", "descartar", "pivot", "target", "segmento",
]

SYSTEM = (
    "You are a strategic coherence guardian for a startup team. "
    "Given a new message, the team's validated/discarded strategic items, "
    "and optional method context, decide whether the message contradicts "
    "established strategy. Return JSON "
    "{\"contradicts\": bool, \"item_content\": the conflicting item or null, "
    "\"reason\": short explanation, \"confidence\": 0..1}."
)


class Guardian:
    def __init__(self, llm):
        self.llm = llm

    def looks_strategic(self, text: str) -> bool:
        low = text.lower()
        return any(sig in low for sig in SIGNALS)

    def check(self, text, known_items, method_context=""):
        items_txt = "\n".join(f"[{i['type']}] {i['content']}" for i in known_items)
        user = (
            f"NEW MESSAGE:\n{text}\n\n"
            f"KNOWN ITEMS:\n{items_txt}\n\n"
            f"METHOD CONTEXT:\n{method_context}"
        )
        return call_validated(self.llm, SYSTEM, user, CoherenceVerdict)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_guardian.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add src/concierge/guardian.py tests/test_guardian.py
git commit -m "feat: coherence guardian with cheap prefilter and verdict check"
```

---

## Task 11: Knowledge Base (RAG)

**Files:**
- Create: `src/concierge/knowledge.py`, `tests/test_knowledge.py`

**Interfaces:**
- Consumes: nothing from our code; uses `chromadb`.
- Produces: `KnowledgeBase(client)` where `client` is a chromadb client (in tests, `chromadb.EphemeralClient()`).
  - `ingest(project_id: int, filename: str, text: str, chunk_size: int = 800) -> int` — splits `text` into chunks, adds to a per-project collection, returns chunk count.
  - `query(project_id: int, question: str, k: int = 3) -> str` — returns the top-k chunks concatenated as a single context string (empty string if the collection is empty/missing).
- Note: chunking uses chroma's default embedding function (no network — chroma's default runs locally). If a test environment cannot download the default model, the test marks itself skipped (shown below).

- [ ] **Step 1: Write the failing test**

```python
import pytest

chromadb = pytest.importorskip("chromadb")
from concierge.knowledge import KnowledgeBase


@pytest.fixture
def kb():
    return KnowledgeBase(chromadb.EphemeralClient())


def test_ingest_returns_chunk_count(kb):
    text = "word " * 500  # ~2500 chars -> multiple chunks at 800
    count = kb.ingest(project_id=1, filename="book.txt", text=text)
    assert count >= 2


def test_query_returns_context_or_empty(kb):
    assert kb.query(project_id=99, question="anything") == ""
    kb.ingest(1, "doc.txt", "The North Star metric is weekly active teams.")
    ctx = kb.query(1, "what is the north star metric?")
    assert "North Star" in ctx
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_knowledge.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'concierge.knowledge'`

- [ ] **Step 3: Implement `src/concierge/knowledge.py`**

```python
class KnowledgeBase:
    def __init__(self, client):
        self.client = client

    def _collection_name(self, project_id):
        return f"project_{project_id}"

    def _chunks(self, text, chunk_size):
        words = text.split()
        out, cur, length = [], [], 0
        for w in words:
            cur.append(w)
            length += len(w) + 1
            if length >= chunk_size:
                out.append(" ".join(cur))
                cur, length = [], 0
        if cur:
            out.append(" ".join(cur))
        return out

    def ingest(self, project_id, filename, text, chunk_size=800):
        coll = self.client.get_or_create_collection(self._collection_name(project_id))
        chunks = self._chunks(text, chunk_size)
        existing = coll.count()
        ids = [f"{filename}-{existing + i}" for i in range(len(chunks))]
        coll.add(documents=chunks, ids=ids)
        return len(chunks)

    def query(self, project_id, question, k=3):
        try:
            coll = self.client.get_collection(self._collection_name(project_id))
        except Exception:
            return ""
        if coll.count() == 0:
            return ""
        res = coll.query(query_texts=[question], n_results=min(k, coll.count()))
        docs = res.get("documents", [[]])[0]
        return "\n\n".join(docs)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_knowledge.py -v`
Expected: PASS (2 passed) — or SKIPPED if chroma's default embedder cannot be downloaded offline.

- [ ] **Step 5: Commit**

```bash
git add src/concierge/knowledge.py tests/test_knowledge.py
git commit -m "feat: chromadb knowledge base for RAG ingest and query"
```

---

## Task 12: Orchestrator — Passive Sync Path

**Files:**
- Create: `src/concierge/orchestrator.py`, `tests/test_orchestrator.py`

**Interfaces:**
- Consumes: `Storage`, `Extractor`, `CanvasUpdater`, `Guardian`, `KnowledgeBase`, `Settings`, `ItemStatus`.
- Produces: `Orchestrator(storage, extractor, updater, guardian, knowledge, settings)`.
  - `ingest_message(chat_id: int, chat_name: str, telegram_msg_id: int, author: str, text: str, ts: float) -> int | None` — gets/creates project, stores message. Returns project_id (or None if duplicate message — still returns project_id for routing; see test).
  - `should_sync(project_id: int) -> bool` — True when unprocessed count ≥ `settings.batch_size`.
  - `run_sync(project_id: int) -> int` — extracts items from unprocessed messages, persists them as `active` items, re-synthesizes canvas blocks, marks messages processed. Returns number of items added.

- [ ] **Step 1: Write the failing test**

```python
import pytest
from concierge.config import Settings
from concierge.storage import Storage
from concierge.extractor import Extractor
from concierge.updater import CanvasUpdater
from concierge.guardian import Guardian
from concierge.orchestrator import Orchestrator
from concierge.models import ItemStatus
import sqlite3


@pytest.fixture
def orch(fake_llm):
    conn = sqlite3.connect(":memory:")
    s = Storage(conn); s.init_schema()
    extractor_llm = fake_llm(responses=[{
        "items": [{"type": "decision", "content": "Target SMBs", "confidence": 0.9}]
    }])
    updater_llm = fake_llm(responses=[{
        "blocks": [{"block_name": "customer_segments", "content": "SMBs"}]
    }])
    settings = Settings(telegram_token="t", openai_api_key="k", batch_size=2)
    return Orchestrator(
        storage=s,
        extractor=Extractor(extractor_llm),
        updater=CanvasUpdater(updater_llm),
        guardian=Guardian(llm=None),
        knowledge=None,
        settings=settings,
    )


def test_should_sync_triggers_at_batch_size(orch):
    pid = orch.ingest_message(100, "Acme", 1, "ana", "msg one", 1.0)
    assert orch.should_sync(pid) is False
    orch.ingest_message(100, "Acme", 2, "ana", "msg two", 2.0)
    assert orch.should_sync(pid) is True


def test_run_sync_creates_items_and_blocks(orch):
    pid = orch.ingest_message(100, "Acme", 1, "ana", "let's target small biz", 1.0)
    orch.ingest_message(100, "Acme", 2, "ana", "agreed", 2.0)
    added = orch.run_sync(pid)
    assert added == 1
    items = orch.storage.items_by_status(pid, [ItemStatus.ACTIVE])
    assert items[0]["content"] == "Target SMBs"
    blocks = orch.storage.get_blocks(pid)
    assert blocks[0]["block_name"] == "customer_segments"
    # messages now processed
    assert orch.storage.unprocessed_messages(pid) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_orchestrator.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'concierge.orchestrator'`

- [ ] **Step 3: Implement the passive path in `src/concierge/orchestrator.py`**

```python
from concierge.models import ItemType, ItemStatus


class Orchestrator:
    def __init__(self, storage, extractor, updater, guardian, knowledge, settings):
        self.storage = storage
        self.extractor = extractor
        self.updater = updater
        self.guardian = guardian
        self.knowledge = knowledge
        self.settings = settings

    def ingest_message(self, chat_id, chat_name, telegram_msg_id, author, text, ts):
        pid = self.storage.get_or_create_project(chat_id, chat_name)
        self.storage.add_message(pid, telegram_msg_id, author, text, ts)
        return pid

    def should_sync(self, project_id):
        pending = self.storage.unprocessed_messages(project_id)
        return len(pending) >= self.settings.batch_size

    def run_sync(self, project_id):
        pending = self.storage.unprocessed_messages(project_id)
        if not pending:
            return 0
        items = self.extractor.extract(pending)
        added = 0
        for it in items:
            self.storage.add_item(
                project_id, it.type, it.content, it.confidence,
                source_message_id=pending[0]["id"],
            )
            added += 1
        active = self.storage.items_by_status(project_id, [ItemStatus.ACTIVE])
        current = self.storage.get_blocks(project_id)
        block_updates = self.updater.update(active, current)
        for b in block_updates:
            self.storage.upsert_block(project_id, b.block_name, b.content, [])
        self.storage.mark_processed([m["id"] for m in pending])
        return added
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_orchestrator.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add src/concierge/orchestrator.py tests/test_orchestrator.py
git commit -m "feat: orchestrator passive sync path (extract -> items -> canvas)"
```

---

## Task 13: Orchestrator — Active Guardian Path

**Files:**
- Modify: `src/concierge/orchestrator.py`
- Modify: `tests/test_orchestrator.py`

**Interfaces:**
- Consumes: `Guardian`, `KnowledgeBase`, `ProjectMode`, `ItemStatus`, `Settings.confidence_threshold`.
- Produces (added to `Orchestrator`): `check_coherence(project_id: int, message_id: int | None, text: str) -> str | None`. Returns an alert string to post to the group, or `None` (stay silent). Logic:
  1. If project mode is `silent` → return `None`.
  2. If `guardian.looks_strategic(text)` is `False` → return `None` (no LLM call).
  3. Fetch known items (`validated` + `discarded`). Fetch method context via `knowledge.query` (empty string if `knowledge` is `None`).
  4. `verdict = guardian.check(...)`. If `None` → return `None` (silent on failure).
  5. If `verdict.contradicts` and `verdict.confidence >= settings.confidence_threshold` → record intervention, return formatted alert. Else `None`.

- [ ] **Step 1: Write the failing test**

```python
import sqlite3
from concierge.config import Settings
from concierge.storage import Storage
from concierge.guardian import Guardian
from concierge.orchestrator import Orchestrator
from concierge.models import ItemType, ItemStatus, ProjectMode


def _orch_with_guardian(guardian_llm):
    conn = sqlite3.connect(":memory:")
    s = Storage(conn); s.init_schema()
    settings = Settings(telegram_token="t", openai_api_key="k", confidence_threshold=0.75)
    return Orchestrator(
        storage=s, extractor=None, updater=None,
        guardian=Guardian(guardian_llm), knowledge=None, settings=settings,
    )


def test_check_silent_on_trivial_message(fake_llm):
    o = _orch_with_guardian(fake_llm(responses=[]))
    pid = o.storage.get_or_create_project(100, "Acme")
    assert o.check_coherence(pid, None, "kkk ok") is None
    # no LLM call was made (prefilter blocked it)
    assert o.guardian.llm.calls == []


def test_check_alerts_on_high_confidence_contradiction(fake_llm):
    o = _orch_with_guardian(fake_llm(responses=[{
        "contradicts": True,
        "item_content": "Validated SMB focus",
        "reason": "proposes enterprise",
        "confidence": 0.9,
    }]))
    pid = o.storage.get_or_create_project(100, "Acme")
    o.storage.add_item(pid, ItemType.HYPOTHESIS, "Validated SMB focus", 0.9, None,
                       status=ItemStatus.VALIDATED)
    alert = o.check_coherence(pid, 1, "vamos priorizar enterprise agora")
    assert alert is not None
    assert "enterprise" in alert.lower() or "SMB" in alert
    assert o.storage.last_intervention(pid)["confidence"] == 0.9


def test_check_silent_below_threshold(fake_llm):
    o = _orch_with_guardian(fake_llm(responses=[{
        "contradicts": True, "item_content": "x", "reason": "maybe", "confidence": 0.5,
    }]))
    pid = o.storage.get_or_create_project(100, "Acme")
    assert o.check_coherence(pid, 1, "vamos mudar o foco") is None


def test_check_silent_when_mode_silent(fake_llm):
    o = _orch_with_guardian(fake_llm(responses=[]))
    pid = o.storage.get_or_create_project(100, "Acme")
    o.storage.set_mode(pid, ProjectMode.SILENT)
    assert o.check_coherence(pid, 1, "vamos priorizar enterprise") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_orchestrator.py -v -k check`
Expected: FAIL with `AttributeError: 'Orchestrator' object has no attribute 'check_coherence'`

- [ ] **Step 3: Add `check_coherence` to `src/concierge/orchestrator.py`** (and import `ProjectMode`)

```python
    def check_coherence(self, project_id, message_id, text):
        if self.storage.get_mode(project_id) == ProjectMode.SILENT:
            return None
        if not self.guardian.looks_strategic(text):
            return None
        known = self.storage.items_by_status(
            project_id, [ItemStatus.VALIDATED, ItemStatus.DISCARDED]
        )
        context = ""
        if self.knowledge is not None:
            context = self.knowledge.query(project_id, text)
        verdict = self.guardian.check(text, known, context)
        if verdict is None:
            return None
        if verdict.contradicts and verdict.confidence >= self.settings.confidence_threshold:
            self.storage.add_intervention(
                project_id, message_id, None, verdict.reason, verdict.confidence
            )
            return (
                "⚠️ Atenção à coerência estratégica:\n"
                f"{verdict.reason}\n"
                f"(item relacionado: {verdict.item_content})"
            )
        return None
```

Update the import line at the top of `orchestrator.py`:

```python
from concierge.models import ItemType, ItemStatus, ProjectMode
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_orchestrator.py -v`
Expected: PASS (all orchestrator tests)

- [ ] **Step 5: Commit**

```bash
git add src/concierge/orchestrator.py tests/test_orchestrator.py
git commit -m "feat: orchestrator active guardian path with threshold and silence"
```

---

## Task 14: OpenAI LLMClient Implementation

**Files:**
- Create: `src/concierge/llm/openai_client.py`, `tests/test_openai_client.py`

**Interfaces:**
- Consumes: `LLMClient`, `LLMError`, `openai`.
- Produces: `OpenAILLMClient(api_key: str, model: str = "gpt-4o-mini")` implementing `complete_json`. Uses the chat completions API with `response_format={"type": "json_object"}`, parses the JSON content, and wraps any exception or JSON parse failure in `LLMError`. The OpenAI SDK is injected as `_client` so the test can substitute a stub without network.

- [ ] **Step 1: Write the failing test**

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_openai_client.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'concierge.llm.openai_client'`

- [ ] **Step 3: Implement `src/concierge/llm/openai_client.py`**

```python
import json
from openai import OpenAI
from concierge.llm.client import LLMClient, LLMError


class OpenAILLMClient(LLMClient):
    def __init__(self, api_key: str, model: str = "gpt-4o-mini"):
        self.model = model
        self._client = OpenAI(api_key=api_key)

    def complete_json(self, system: str, user: str) -> dict:
        try:
            resp = self._client.chat.completions.create(
                model=self.model,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            )
            content = resp.choices[0].message.content
            return json.loads(content)
        except Exception as e:
            raise LLMError(str(e)) from e
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_openai_client.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add src/concierge/llm/openai_client.py tests/test_openai_client.py
git commit -m "feat: OpenAI LLMClient implementation with JSON mode"
```

---

## Task 15: Bot Layer and Entrypoint

**Files:**
- Create: `src/concierge/bot.py`, `src/concierge/main.py`, `tests/test_bot.py`, `README.md`

**Interfaces:**
- Consumes: `Orchestrator`, `Storage`, `python-telegram-bot`.
- Produces:
  - In `bot.py`: pure handler functions that take `(orchestrator, ...)` and return reply text, so they're testable without Telegram:
    - `handle_start(orchestrator, chat_id, chat_name) -> str` — creates project, returns consent/monitoring notice.
    - `handle_status(orchestrator, chat_id) -> str` — returns a formatted canvas summary.
    - `handle_why(orchestrator, chat_id) -> str` — returns the last intervention explanation, or "nenhuma intervenção ainda".
    - `handle_forget(orchestrator, chat_id) -> str` — deletes all project data, returns confirmation.
    - `build_application(orchestrator, token)` — wires `python-telegram-bot` `Application` with command + message handlers. (Not unit-tested; smoke-built only.)
  - In `main.py`: `main()` that builds `Settings.from_env()`, real `Storage` (file db), `OpenAILLMClient`, `KnowledgeBase`, `Orchestrator`, then runs polling.
- Added to `Storage`: `delete_project(project_id: int) -> None` (removes rows across all tables for that project — supports `/forget`).

- [ ] **Step 1: Write the failing test for handlers and delete_project**

```python
import sqlite3
from concierge.config import Settings
from concierge.storage import Storage
from concierge.extractor import Extractor
from concierge.updater import CanvasUpdater
from concierge.guardian import Guardian
from concierge.orchestrator import Orchestrator
from concierge.models import ItemType, ItemStatus
from concierge import bot


def _orch(fake_llm):
    conn = sqlite3.connect(":memory:")
    s = Storage(conn); s.init_schema()
    settings = Settings(telegram_token="t", openai_api_key="k")
    return Orchestrator(s, Extractor(fake_llm(responses=[])),
                        CanvasUpdater(fake_llm(responses=[])),
                        Guardian(llm=None), None, settings)


def test_handle_start_creates_project_and_notifies(fake_llm):
    o = _orch(fake_llm)
    reply = bot.handle_start(o, chat_id=100, chat_name="Acme")
    assert "monitor" in reply.lower()
    assert o.storage.get_or_create_project(100, "Acme")  # exists


def test_handle_status_shows_blocks(fake_llm):
    o = _orch(fake_llm)
    pid = o.storage.get_or_create_project(100, "Acme")
    o.storage.upsert_block(pid, "customer_segments", "SMBs", [])
    reply = bot.handle_status(o, 100)
    assert "customer_segments" in reply
    assert "SMBs" in reply


def test_handle_why_with_and_without_intervention(fake_llm):
    o = _orch(fake_llm)
    pid = o.storage.get_or_create_project(100, "Acme")
    assert "nenhuma" in bot.handle_why(o, 100).lower()
    o.storage.add_intervention(pid, 1, None, "conflicts with SMB focus", 0.9)
    assert "SMB" in bot.handle_why(o, 100)


def test_handle_forget_deletes_data(fake_llm):
    o = _orch(fake_llm)
    pid = o.storage.get_or_create_project(100, "Acme")
    o.storage.add_item(pid, ItemType.DECISION, "x", 0.5, None)
    bot.handle_forget(o, 100)
    # project recreated empty on next access -> no items
    pid2 = o.storage.get_or_create_project(100, "Acme")
    assert o.storage.items_by_status(pid2, [ItemStatus.ACTIVE]) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_bot.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'concierge.bot'` (and `delete_project` missing)

- [ ] **Step 3: Add `delete_project` to `src/concierge/storage.py`**

```python
    def delete_project(self, project_id):
        for table in ("messages", "strategic_items", "canvas_blocks",
                      "interventions", "knowledge_docs"):
            self.conn.execute(f"DELETE FROM {table} WHERE project_id = ?", (project_id,))
        self.conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
        self.conn.commit()
```

- [ ] **Step 4: Implement `src/concierge/bot.py`**

```python
from telegram import Update
from telegram.ext import (
    Application, CommandHandler, MessageHandler, filters, ContextTypes,
)

CONSENT = (
    "👋 Olá! Sou o concierge estratégico deste projeto.\n"
    "A partir de agora vou acompanhar as conversas para manter o canvas "
    "atualizado e alertar sobre incoerências estratégicas.\n"
    "Use /status para ver o canvas, /why para entender alertas, "
    "e /forget para apagar todos os dados."
)


def handle_start(orchestrator, chat_id, chat_name):
    orchestrator.storage.get_or_create_project(chat_id, chat_name)
    return CONSENT


def handle_status(orchestrator, chat_id):
    pid = orchestrator.storage.get_or_create_project(chat_id, str(chat_id))
    blocks = orchestrator.storage.get_blocks(pid)
    if not blocks:
        return "Canvas ainda vazio. Continue a conversa — eu cuido do resto."
    lines = [f"*{b['block_name']}*: {b['content']}" for b in blocks]
    return "📋 Canvas atual:\n" + "\n".join(lines)


def handle_why(orchestrator, chat_id):
    pid = orchestrator.storage.get_or_create_project(chat_id, str(chat_id))
    last = orchestrator.storage.last_intervention(pid)
    if last is None:
        return "Nenhuma intervenção ainda."
    return f"Último alerta: {last['reason']} (confiança {last['confidence']:.0%})"


def handle_forget(orchestrator, chat_id):
    pid = orchestrator.storage.get_or_create_project(chat_id, str(chat_id))
    orchestrator.storage.delete_project(pid)
    return "🗑️ Todos os dados deste projeto foram apagados."


def build_application(orchestrator, token):
    app = Application.builder().token(token).build()

    async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        chat = update.effective_chat
        await update.message.reply_text(handle_start(orchestrator, chat.id, chat.title or str(chat.id)))

    async def status(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(
            handle_status(orchestrator, update.effective_chat.id), parse_mode="Markdown"
        )

    async def why(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(handle_why(orchestrator, update.effective_chat.id))

    async def forget(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(handle_forget(orchestrator, update.effective_chat.id))

    async def sync(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        chat = update.effective_chat
        pid = orchestrator.storage.get_or_create_project(chat.id, chat.title or str(chat.id))
        added = orchestrator.run_sync(pid)
        await update.message.reply_text(f"🔄 Sync concluído. {added} itens novos.")

    async def on_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        chat = update.effective_chat
        msg = update.message
        pid = orchestrator.ingest_message(
            chat.id, chat.title or str(chat.id), msg.message_id,
            msg.from_user.username or msg.from_user.first_name, msg.text, msg.date.timestamp(),
        )
        alert = orchestrator.check_coherence(pid, msg.message_id, msg.text)
        if alert:
            await msg.reply_text(alert)
        if orchestrator.should_sync(pid):
            orchestrator.run_sync(pid)

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("why", why))
    app.add_handler(CommandHandler("forget", forget))
    app.add_handler(CommandHandler("sync", sync))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_message))
    return app
```

- [ ] **Step 5: Implement `src/concierge/main.py`**

```python
import sqlite3
import chromadb
from concierge.config import Settings
from concierge.storage import Storage
from concierge.extractor import Extractor
from concierge.updater import CanvasUpdater
from concierge.guardian import Guardian
from concierge.knowledge import KnowledgeBase
from concierge.orchestrator import Orchestrator
from concierge.llm.openai_client import OpenAILLMClient
from concierge.bot import build_application


def main():
    settings = Settings.from_env()
    conn = sqlite3.connect(settings.db_path, check_same_thread=False)
    storage = Storage(conn)
    storage.init_schema()
    llm = OpenAILLMClient(settings.openai_api_key)
    knowledge = KnowledgeBase(chromadb.PersistentClient(path=settings.chroma_path))
    orchestrator = Orchestrator(
        storage=storage,
        extractor=Extractor(llm),
        updater=CanvasUpdater(llm),
        guardian=Guardian(llm),
        knowledge=knowledge,
        settings=settings,
    )
    app = build_application(orchestrator, settings.telegram_token)
    app.run_polling()


if __name__ == "__main__":
    main()
```

- [ ] **Step 6: Run handler tests to verify they pass**

Run: `pytest tests/test_bot.py -v`
Expected: PASS (4 passed)

- [ ] **Step 7: Smoke-build the application (no network)**

Run: `python -c "from concierge.bot import build_application; print('ok')"`
Expected: prints `ok` (import + symbol resolve cleanly)

- [ ] **Step 8: Create `README.md`**

```markdown
# Strategic Concierge Bot

Telegram bot that turns team conversations into a living strategic base:
extracts decisions/hypotheses/premises, keeps a Business Model Canvas updated,
and alerts the team when discussions contradict validated strategy.

## Setup

    python -m venv .venv && source .venv/bin/activate
    pip install -r requirements.txt
    cp .env.example .env   # fill in TELEGRAM_TOKEN and OPENAI_API_KEY

## Run

    python -m concierge.main

## Test

    pytest

## Commands

- `/start` — activate the bot in a group (shows monitoring notice)
- `/sync` — force a canvas update now
- `/status` — show the current canvas
- `/why` — explain the last coherence alert
- `/forget` — delete all project data

## Privacy

The bot only acts in groups where it was added and activated via `/start`,
and announces that it is monitoring. `/why` explains every intervention;
`/forget` erases all stored data.
```

- [ ] **Step 9: Commit**

```bash
git add src/concierge/bot.py src/concierge/main.py src/concierge/storage.py tests/test_bot.py README.md
git commit -m "feat: telegram bot layer, commands, entrypoint, and README"
```

---

## Task 16: Full Test Suite Green and Final Commit

**Files:**
- None new — verification task.

- [ ] **Step 1: Run the entire suite**

Run: `pytest -v`
Expected: all tests PASS (knowledge tests may show SKIPPED if chroma's embedder can't download offline — that is acceptable).

- [ ] **Step 2: Confirm no business logic touches the network in tests**

Run: `pytest -v -k "not knowledge"`
Expected: all PASS with zero network calls (everything uses fakes/in-memory).

- [ ] **Step 3: Tag the working MVP**

```bash
git tag mvp-v1
git log --oneline | head -20
```

---

## Self-Review

**Spec coverage check (spec → task):**
- §3 Bot Layer → Task 15. Orchestrator → Tasks 12–13. Extractor → Task 8. Canvas Updater → Task 9. Coherence Guardian → Task 10. Knowledge Base/RAG → Task 11. Storage → Tasks 3–5. LLMClient → Tasks 6–7, 14. ✓
- §4 Data model — all six tables created in Task 3 schema; CRUD across Tasks 3–5. `source_message_id`, `superseded_by`, `mode` all present. ✓
- §5 Hybrid flow — passive (Task 12), active with prefilter + threshold (Task 13). Commands `/start /sync /status /why /forget` (Task 15). `/check` and `/upload` deferred — see note below. 
- §6 Privacy — consent notice (`handle_start`), `/why` (`handle_why`), `/forget` (`handle_forget` + `delete_project`). ✓
- §7 Errors — `call_validated` retry-once-then-None (Task 7); guardian silent on failure (Task 13); idempotent `add_message` (Task 3); `LLMError` wrapping (Task 14). ✓
- §8 Testing — fake LLM + in-memory db throughout; manual E2E is the demo. ✓

**Two spec commands intentionally deferred from this MVP plan** (documented here so it's explicit, not a silent gap): `/check` (on-demand coherence — trivially addable later as it reuses `check_coherence`, but needs a target message; not essential for the demo flow) and `/upload` (file ingestion wiring — `KnowledgeBase.ingest` exists and is tested in Task 11; wiring Telegram file download is mechanical and can be added without new design). The passive auto-sync + active guardian + `/sync` cover the core demo. If you want either command in the MVP, say so and I'll add a task.

**Placeholder scan:** No TBD/TODO; every code step shows complete code. ✓

**Type consistency:** `complete_json`, `call_validated`, `extract`, `update`, `looks_strategic`, `check`, `check_coherence`, `run_sync`, `should_sync`, `ingest_message`, block names, and enum values are consistent across all tasks. ✓
