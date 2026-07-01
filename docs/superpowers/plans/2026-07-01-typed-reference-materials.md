# Typed Reference Materials Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `/upload` ingests reference materials (PDF/TXT/MD/DOCX/pasted text), auto-classifies them by type via LLM, and routes each type to the right analysis modules — so each material incrementally unlocks a specific capability.

**Architecture:** A new `materials.py` module owns parsing, classification, and the type→module routing table. `KnowledgeBase` gains typed metadata on chunks and filtered queries. Extractor/Updater/Reconciler gain an optional `context` param (Guardian already has one); the Orchestrator queries the knowledge base with each module's type filter and injects the context. Bot handlers stay pure; the async glue downloads files.

**Tech Stack:** Python 3.14, pypdf 6.14.2, python-docx 1.2.0, ChromaDB 1.5.9 (metadata filters), Pydantic, existing LLMClient/call_validated.

## Global Constraints

- All LLM calls go through `call_validated` (retry-once-then-discard); never call SDKs directly from business logic.
- Classification failure → fallback `MaterialType.GENERIC`; ingestion never aborts because of classification.
- Parser failure → friendly chat message, nothing persisted.
- File size cap: 20 MB (Telegram Bot API limit).
- All business logic testable without network (fake LLM, ephemeral Chroma, in-memory SQLite).
- Commands require the `/start` consent gate (existing `NOT_STARTED` pattern).
- Shared venv: `. .venv/bin/activate` at repo root, Python 3.14.3. Run tests from repo root.
- `MaterialType` values exactly: `canvas_guide`, `validation_guide`, `methodology`, `custom_framework`, `generic`.
- Routing (type → modules): canvas_guide→{updater}; validation_guide→{guardian, reconciler}; methodology→{extractor, guardian}; custom_framework→{extractor, updater, guardian, reconciler}; generic→{guardian}.

---

## File Structure

```
src/concierge/
  materials.py        # NEW: extract_text, classify, ROUTING, CAPABILITIES,
                      #      types_for_module, MaterialService, MaterialError
  models.py           # +MaterialType enum, +ClassificationResult schema
  storage.py          # +material_type column, +add_knowledge_doc, +list_knowledge_docs
  knowledge.py        # ingest(+material_type), query(+material_types filter), +delete
  extractor.py        # extract(+context="")
  updater.py          # update(+context="")
  reconciler.py       # reconcile(+context="")
  orchestrator.py     # typed RAG queries injected into run_sync/check_coherence
  bot.py              # /upload (doc + text), /materials, /forget drops chroma
  main.py             # builds MaterialService, passes to build_application
tests/
  test_materials.py   # NEW
  + additions to test_models/test_storage/test_knowledge/test_extractor/
    test_updater/test_reconciler/test_orchestrator/test_bot
requirements.txt      # +pypdf==6.14.2, +python-docx==1.2.0
```

---

### Task 1: MaterialType enum, ClassificationResult schema, dependencies

**Files:**
- Modify: `src/concierge/models.py`
- Modify: `tests/test_models.py`
- Modify: `requirements.txt`

**Interfaces:**
- Produces: `MaterialType(str, Enum)` with values `CANVAS_GUIDE="canvas_guide"`, `VALIDATION_GUIDE="validation_guide"`, `METHODOLOGY="methodology"`, `CUSTOM_FRAMEWORK="custom_framework"`, `GENERIC="generic"`. `ClassificationResult(BaseModel)` with `material_type: MaterialType`.

- [ ] **Step 1: Write the failing test** — append to `tests/test_models.py`:

```python
def test_material_type_values():
    from concierge.models import MaterialType
    assert {t.value for t in MaterialType} == {
        "canvas_guide", "validation_guide", "methodology",
        "custom_framework", "generic",
    }


def test_classification_result_parses_and_rejects():
    from concierge.models import ClassificationResult, MaterialType
    ok = ClassificationResult.model_validate({"material_type": "validation_guide"})
    assert ok.material_type == MaterialType.VALIDATION_GUIDE
    with pytest.raises(ValidationError):
        ClassificationResult.model_validate({"material_type": "cookbook"})
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_models.py -v -k material`
Expected: FAIL with `ImportError: cannot import name 'MaterialType'`

- [ ] **Step 3: Implement** — append to `src/concierge/models.py`:

```python
class MaterialType(str, Enum):
    CANVAS_GUIDE = "canvas_guide"
    VALIDATION_GUIDE = "validation_guide"
    METHODOLOGY = "methodology"
    CUSTOM_FRAMEWORK = "custom_framework"
    GENERIC = "generic"


class ClassificationResult(BaseModel):
    material_type: MaterialType
```

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/test_models.py -v`
Expected: PASS (all)

- [ ] **Step 5: Add dependencies** — append to `requirements.txt`:

```
pypdf==6.14.2
python-docx==1.2.0
```

(Both already verified to install as wheels on Python 3.14; the shared venv already has them.)

- [ ] **Step 6: Commit**

```bash
git add src/concierge/models.py tests/test_models.py requirements.txt
git commit -m "feat: MaterialType enum, classification schema, parser deps"
```

---

### Task 2: Storage — typed knowledge_docs

**Files:**
- Modify: `src/concierge/storage.py`
- Modify: `tests/test_storage.py`

**Interfaces:**
- Consumes: existing `Storage`, `SCHEMA` string, `init_schema`.
- Produces: `add_knowledge_doc(project_id: int, filename: str, material_type: str, chunk_count: int) -> int`; `list_knowledge_docs(project_id: int) -> list[dict]` (each: `id, filename, material_type, chunk_count, uploaded_at`, ordered by `uploaded_at` then `id`).

- [ ] **Step 1: Write the failing test** — append to `tests/test_storage.py`:

```python
def test_knowledge_doc_roundtrip_with_type(storage):
    pid = storage.get_or_create_project(100, "Acme")
    storage.add_knowledge_doc(pid, "manual-bmc.pdf", "canvas_guide", 12)
    storage.add_knowledge_doc(pid, "notas.txt", "generic", 3)
    docs = storage.list_knowledge_docs(pid)
    assert len(docs) == 2
    assert docs[0]["filename"] == "manual-bmc.pdf"
    assert docs[0]["material_type"] == "canvas_guide"
    assert docs[0]["chunk_count"] == 12
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_storage.py -v -k knowledge_doc`
Expected: FAIL with `AttributeError: 'Storage' object has no attribute 'add_knowledge_doc'`

- [ ] **Step 3: Implement** — in `src/concierge/storage.py`:

3a. In the `SCHEMA` string, change the `knowledge_docs` table to include the column:

```sql
CREATE TABLE IF NOT EXISTS knowledge_docs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL,
    filename TEXT NOT NULL,
    material_type TEXT NOT NULL DEFAULT 'generic',
    uploaded_at REAL NOT NULL DEFAULT (strftime('%s','now')),
    chunk_count INTEGER NOT NULL DEFAULT 0
);
```

3b. At the end of `init_schema`, add a migration guard for pre-existing databases (the CREATE above is IF NOT EXISTS, so old DBs keep the old shape):

```python
    def init_schema(self) -> None:
        self.conn.executescript(SCHEMA)
        try:
            self.conn.execute(
                "ALTER TABLE knowledge_docs ADD COLUMN material_type TEXT NOT NULL DEFAULT 'generic'"
            )
        except sqlite3.OperationalError:
            pass  # column already exists
        self.conn.commit()
```

3c. Append the two methods inside `Storage`:

```python
    def add_knowledge_doc(self, project_id: int, filename: str,
                          material_type: str, chunk_count: int) -> int:
        cur = self.conn.execute(
            "INSERT INTO knowledge_docs (project_id, filename, material_type, chunk_count) "
            "VALUES (?, ?, ?, ?)",
            (project_id, filename, material_type, chunk_count),
        )
        self.conn.commit()
        return cur.lastrowid

    def list_knowledge_docs(self, project_id: int) -> list[dict]:
        cur = self.conn.execute(
            "SELECT id, filename, material_type, chunk_count, uploaded_at "
            "FROM knowledge_docs WHERE project_id = ? ORDER BY uploaded_at, id",
            (project_id,),
        )
        return [dict(r) for r in cur.fetchall()]
```

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/test_storage.py -v`
Expected: PASS (all)

- [ ] **Step 5: Commit**

```bash
git add src/concierge/storage.py tests/test_storage.py
git commit -m "feat: typed knowledge_docs storage with migration guard"
```

---

### Task 3: KnowledgeBase — typed ingest, filtered query, delete

**Files:**
- Modify: `src/concierge/knowledge.py`
- Modify: `tests/test_knowledge.py`

**Interfaces:**
- Consumes: existing `KnowledgeBase` (chroma client injected).
- Produces:
  - `ingest(project_id, filename, text, chunk_size=800, material_type="generic") -> int` — every chunk gets metadata `{"material_type": material_type}`.
  - `query(project_id, question, k=3, material_types: list[str] | None = None) -> str` — when `material_types` is given, applies chroma `where={"material_type": {"$in": material_types}}`.
  - `delete(project_id) -> None` — drops the project collection; silent if missing.

- [ ] **Step 1: Write the failing test** — append to `tests/test_knowledge.py`:

```python
def test_typed_ingest_and_filtered_query(kb):
    kb.ingest(1, "bmc.txt", "The nine building blocks of the canvas.",
              material_type="canvas_guide")
    kb.ingest(1, "val.txt", "Run experiments with five customers first.",
              material_type="validation_guide")
    only_canvas = kb.query(1, "canvas blocks", material_types=["canvas_guide"])
    assert "building blocks" in only_canvas
    assert "experiments" not in only_canvas
    only_val = kb.query(1, "experiments", material_types=["validation_guide"])
    assert "experiments" in only_val


def test_unfiltered_query_still_sees_everything(kb):
    kb.ingest(1, "a.txt", "alpha content here", material_type="canvas_guide")
    assert "alpha" in kb.query(1, "alpha content")


def test_delete_drops_collection(kb):
    kb.ingest(1, "a.txt", "some text to remember", material_type="generic")
    kb.delete(1)
    assert kb.query(1, "anything") == ""
    kb.delete(1)  # deleting again is silent
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_knowledge.py -v -k "typed or delete or unfiltered"`
Expected: FAIL with `TypeError: ingest() got an unexpected keyword argument 'material_type'`

- [ ] **Step 3: Implement** — replace `ingest`/`query` and add `delete` in `src/concierge/knowledge.py`:

```python
    def ingest(self, project_id, filename, text, chunk_size=800,
               material_type="generic"):
        coll = self.client.get_or_create_collection(self._collection_name(project_id))
        chunks = self._chunks(text, chunk_size)
        existing = coll.count()
        ids = [f"{filename}-{existing + i}" for i in range(len(chunks))]
        coll.add(
            documents=chunks,
            ids=ids,
            metadatas=[{"material_type": material_type}] * len(chunks),
        )
        return len(chunks)

    def query(self, project_id, question, k=3, material_types=None):
        try:
            coll = self.client.get_collection(self._collection_name(project_id))
        except Exception:
            return ""
        total = coll.count()
        if total == 0:
            return ""
        kwargs = {"query_texts": [question], "n_results": min(k, total)}
        if material_types:
            kwargs["where"] = {"material_type": {"$in": list(material_types)}}
        res = coll.query(**kwargs)
        docs = res.get("documents", [[]])[0]
        return "\n\n".join(docs)

    def delete(self, project_id):
        try:
            self.client.delete_collection(self._collection_name(project_id))
        except Exception:
            pass
```

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/test_knowledge.py -v`
Expected: PASS (all — old tests unaffected: default `material_type="generic"`, no filter by default)

- [ ] **Step 5: Commit**

```bash
git add src/concierge/knowledge.py tests/test_knowledge.py
git commit -m "feat: typed chunks, filtered queries, and delete in KnowledgeBase"
```

---

### Task 4: materials.py — text extraction (parsers)

**Files:**
- Create: `src/concierge/materials.py`
- Create: `tests/test_materials.py`

**Interfaces:**
- Produces: `MaterialError(Exception)`; `extract_text(filename: str, data: bytes) -> str` supporting `.pdf` (pypdf), `.txt`/`.md` (utf-8 with latin-1 fallback), `.docx` (python-docx); unsupported extension raises `MaterialError` with a friendly message; empty extracted text raises `MaterialError`.

- [ ] **Step 1: Write the failing test** — create `tests/test_materials.py`:

```python
import io
import pytest
from concierge.materials import extract_text, MaterialError


def _pdf_bytes(text):
    from pypdf import PdfWriter
    import io as _io
    w = PdfWriter()
    page = w.add_blank_page(width=200, height=200)
    # pypdf can't easily write text; use a txt-based assertion for pdf via
    # a real minimal pdf produced by reportlab-free approach: instead test
    # that a blank pdf raises MaterialError for empty text.
    buf = _io.BytesIO()
    w.write(buf)
    return buf.getvalue()


def _docx_bytes(text):
    import docx, io as _io
    d = docx.Document()
    d.add_paragraph(text)
    buf = _io.BytesIO()
    d.save(buf)
    return buf.getvalue()


def test_txt_and_md_extraction():
    assert extract_text("notas.txt", "olá mundo".encode()) == "olá mundo"
    assert extract_text("guia.md", b"# Title\nbody") == "# Title\nbody"


def test_txt_latin1_fallback():
    assert "ção" in extract_text("legado.txt", "validação".encode("latin-1"))


def test_docx_extraction():
    data = _docx_bytes("Business Model Canvas em nove blocos")
    assert "nove blocos" in extract_text("manual.docx", data)


def test_blank_pdf_raises_empty():
    with pytest.raises(MaterialError):
        extract_text("vazio.pdf", _pdf_bytes(""))


def test_unsupported_extension_raises():
    with pytest.raises(MaterialError):
        extract_text("planilha.xlsx", b"whatever")
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_materials.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'concierge.materials'`

- [ ] **Step 3: Implement** — create `src/concierge/materials.py`:

```python
import io


class MaterialError(Exception):
    """User-facing ingestion problem (unsupported format, unreadable file)."""


def _from_pdf(data: bytes) -> str:
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(data))
    return "\n".join((page.extract_text() or "") for page in reader.pages)


def _from_docx(data: bytes) -> str:
    import docx
    document = docx.Document(io.BytesIO(data))
    return "\n".join(p.text for p in document.paragraphs)


def _from_text(data: bytes) -> str:
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("latin-1")


_PARSERS = {".pdf": _from_pdf, ".docx": _from_docx, ".txt": _from_text, ".md": _from_text}


def extract_text(filename: str, data: bytes) -> str:
    ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    parser = _PARSERS.get(ext)
    if parser is None:
        raise MaterialError(
            f"Formato não suportado: '{ext or filename}'. Aceito: PDF, TXT, MD, DOCX."
        )
    try:
        text = parser(data)
    except MaterialError:
        raise
    except Exception as e:
        raise MaterialError(f"Não consegui ler o arquivo '{filename}': {e}") from e
    if not text.strip():
        raise MaterialError(f"O arquivo '{filename}' não contém texto extraível.")
    return text
```

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/test_materials.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add src/concierge/materials.py tests/test_materials.py
git commit -m "feat: material text extraction for pdf/txt/md/docx"
```

---

### Task 5: materials.py — classification, routing, MaterialService

**Files:**
- Modify: `src/concierge/materials.py`
- Modify: `tests/test_materials.py`

**Interfaces:**
- Consumes: `call_validated`, `ClassificationResult`, `MaterialType`, `KnowledgeBase`, `Storage` (Task 2 methods).
- Produces:
  - `ROUTING: dict[MaterialType, set[str]]` exactly per Global Constraints.
  - `CAPABILITIES: dict[MaterialType, str]` — announcement strings (Portuguese, below).
  - `types_for_module(module: str) -> list[str]` — inverted routing, module names: `"extractor"`, `"updater"`, `"guardian"`, `"reconciler"`.
  - `classify(llm, filename: str, text: str) -> MaterialType` — LLM on first 2000 chars; `None` → `GENERIC`.
  - `MaterialService(llm, knowledge, storage)` with `add_material(project_id: int, filename: str, text: str) -> tuple[MaterialType, int]` — classify → `knowledge.ingest(..., material_type=...)` → `storage.add_knowledge_doc(...)` → returns `(type, chunk_count)`.

- [ ] **Step 1: Write the failing test** — append to `tests/test_materials.py`:

```python
import chromadb
import sqlite3
from concierge.materials import (
    classify, types_for_module, ROUTING, CAPABILITIES, MaterialService,
)
from concierge.models import MaterialType
from concierge.storage import Storage
from concierge.knowledge import KnowledgeBase


def test_routing_covers_all_types_and_inverts():
    assert set(ROUTING) == set(MaterialType)
    assert set(CAPABILITIES) == set(MaterialType)
    assert "updater" in ROUTING[MaterialType.CANVAS_GUIDE]
    guardian_types = types_for_module("guardian")
    assert set(guardian_types) == {
        "validation_guide", "methodology", "custom_framework", "generic"
    }
    assert types_for_module("updater") == sorted(["canvas_guide", "custom_framework"]) or \
        set(types_for_module("updater")) == {"canvas_guide", "custom_framework"}


def test_classify_returns_type_and_falls_back(fake_llm):
    llm = fake_llm(responses=[{"material_type": "validation_guide"}])
    assert classify(llm, "guia.pdf", "como validar hipóteses...") == MaterialType.VALIDATION_GUIDE
    bad = fake_llm(responses=[{"material_type": "zzz"}, {"material_type": "zzz"}])
    assert classify(bad, "x.txt", "abc") == MaterialType.GENERIC


def test_material_service_end_to_end(fake_llm):
    conn = sqlite3.connect(":memory:")
    st = Storage(conn); st.init_schema()
    pid = st.get_or_create_project(100, "Acme")
    kb = KnowledgeBase(chromadb.EphemeralClient())
    llm = fake_llm(responses=[{"material_type": "canvas_guide"}])
    svc = MaterialService(llm, kb, st)
    mtype, chunks = svc.add_material(pid, "manual.txt", "os nove blocos do canvas " * 50)
    assert mtype == MaterialType.CANVAS_GUIDE
    assert chunks >= 1
    docs = st.list_knowledge_docs(pid)
    assert docs[0]["material_type"] == "canvas_guide"
    assert "blocos" in kb.query(pid, "blocos", material_types=["canvas_guide"])
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_materials.py -v -k "routing or classify or service"`
Expected: FAIL with `ImportError: cannot import name 'classify'`

- [ ] **Step 3: Implement** — append to `src/concierge/materials.py`:

```python
from concierge.llm.client import call_validated
from concierge.models import ClassificationResult, MaterialType

ROUTING = {
    MaterialType.CANVAS_GUIDE: {"updater"},
    MaterialType.VALIDATION_GUIDE: {"guardian", "reconciler"},
    MaterialType.METHODOLOGY: {"extractor", "guardian"},
    MaterialType.CUSTOM_FRAMEWORK: {"extractor", "updater", "guardian", "reconciler"},
    MaterialType.GENERIC: {"guardian"},
}

CAPABILITIES = {
    MaterialType.CANVAS_GUIDE: "o canvas passa a seguir as definições deste manual",
    MaterialType.VALIDATION_GUIDE: "o guardião agora cobra experimentos; validações seguem este método",
    MaterialType.METHODOLOGY: "as análises passam a usar os conceitos deste método",
    MaterialType.CUSTOM_FRAMEWORK: "este framework vira lente de todas as análises",
    MaterialType.GENERIC: "material disponível como contexto geral",
}

CLASSIFY_SYSTEM = (
    "You classify startup reference material. Given a filename and the opening "
    "text, return JSON {\"material_type\": one of canvas_guide|validation_guide|"
    "methodology|custom_framework|generic}. canvas_guide = manuals about business "
    "model canvas blocks; validation_guide = how to validate hypotheses/run "
    "experiments; methodology = named methods like Design Thinking or Lean; "
    "custom_framework = the team's own internal framework; generic = anything else."
)


def types_for_module(module: str) -> list[str]:
    return sorted(t.value for t, mods in ROUTING.items() if module in mods)


def classify(llm, filename: str, text: str) -> MaterialType:
    user = f"FILENAME: {filename}\n\nOPENING TEXT:\n{text[:2000]}"
    result = call_validated(llm, CLASSIFY_SYSTEM, user, ClassificationResult)
    if result is None:
        return MaterialType.GENERIC
    return result.material_type


class MaterialService:
    def __init__(self, llm, knowledge, storage):
        self.llm = llm
        self.knowledge = knowledge
        self.storage = storage

    def add_material(self, project_id: int, filename: str, text: str):
        mtype = classify(self.llm, filename, text)
        chunks = self.knowledge.ingest(
            project_id, filename, text, material_type=mtype.value
        )
        self.storage.add_knowledge_doc(project_id, filename, mtype.value, chunks)
        return mtype, chunks
```

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/test_materials.py -v`
Expected: PASS (all)

- [ ] **Step 5: Commit**

```bash
git add src/concierge/materials.py tests/test_materials.py
git commit -m "feat: material classification, routing table, and MaterialService"
```

---

### Task 6: context param on Extractor, CanvasUpdater, Reconciler

**Files:**
- Modify: `src/concierge/extractor.py`, `src/concierge/updater.py`, `src/concierge/reconciler.py`
- Modify: `tests/test_extractor.py`, `tests/test_updater.py`, `tests/test_reconciler.py`

**Interfaces:**
- Consumes: current signatures `Extractor.extract(messages)`, `CanvasUpdater.update(active_items, current_blocks)`, `Reconciler.reconcile(new_items, active_items)`.
- Produces: each gains trailing kwarg `context: str = ""`. When non-empty, the user prompt gains a final block `\n\nREFERENCE MATERIAL:\n{context}`. Empty context → prompt byte-identical to today (backward compatible).

- [ ] **Step 1: Write the failing tests** — append one test per file:

`tests/test_extractor.py`:
```python
def test_extract_appends_reference_material(fake_llm):
    llm = fake_llm(responses=[{"items": []}])
    Extractor(llm).extract(
        [{"author": "ana", "text": "oi"}], context="use o método X"
    )
    assert "REFERENCE MATERIAL:\nuse o método X" in llm.calls[0][1]
```

`tests/test_updater.py`:
```python
def test_update_appends_reference_material(fake_llm):
    llm = fake_llm(responses=[{"blocks": []}])
    CanvasUpdater(llm).update([], [], context="manual do canvas diz Y")
    assert "REFERENCE MATERIAL:\nmanual do canvas diz Y" in llm.calls[0][1]
```

`tests/test_reconciler.py`:
```python
def test_reconcile_appends_reference_material(fake_llm):
    llm = fake_llm(responses=[{"transitions": []}])
    Reconciler(llm).reconcile([{"id": 1, "type": "decision", "content": "x"}], [],
                              context="valide com 5 clientes")
    assert "REFERENCE MATERIAL:\nvalide com 5 clientes" in llm.calls[0][1]
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_extractor.py tests/test_updater.py tests/test_reconciler.py -v -k reference`
Expected: FAIL ×3 with `TypeError: ... unexpected keyword argument 'context'`

- [ ] **Step 3: Implement** — same mechanical change in each:

`extractor.py` — `extract` becomes:
```python
    def extract(self, messages, context=""):
        transcript = "\n".join(f"{m['author']}: {m['text']}" for m in messages)
        if context:
            transcript += f"\n\nREFERENCE MATERIAL:\n{context}"
        result = call_validated(self.llm, SYSTEM, transcript, ExtractionResult)
        if result is None:
            return []
        return result.items
```

`updater.py` — inside `update`, after building `user`:
```python
    def update(self, active_items, current_blocks, context=""):
        items_txt = "\n".join(f"[{i['type']}] {i['content']}" for i in active_items)
        blocks_txt = "\n".join(f"{b['block_name']}: {b['content']}" for b in current_blocks)
        user = f"STRATEGIC ITEMS:\n{items_txt}\n\nCURRENT CANVAS:\n{blocks_txt}"
        if context:
            user += f"\n\nREFERENCE MATERIAL:\n{context}"
        result = call_validated(self.llm, SYSTEM, user, CanvasUpdateResult)
        if result is None:
            return []
        return [b for b in result.blocks if b.block_name in BMC_BLOCKS]
```

`reconciler.py` — inside `reconcile`, after building `user`:
```python
    def reconcile(self, new_items, active_items, context=""):
        known_ids = {i["id"] for i in new_items} | {i["id"] for i in active_items}
        new_txt = "\n".join(f"#{i['id']} [{i['type']}] {i['content']}" for i in new_items)
        active_txt = "\n".join(f"#{i['id']} [{i['type']}] {i['content']}" for i in active_items)
        user = f"NEW ITEMS:\n{new_txt}\n\nEXISTING ACTIVE ITEMS:\n{active_txt}"
        if context:
            user += f"\n\nREFERENCE MATERIAL:\n{context}"
        result = call_validated(self.llm, SYSTEM, user, ReconciliationResult)
        if result is None:
            return []
        return [
            t for t in result.transitions
            if t.new_status in _ALLOWED and t.item_id in known_ids
        ]
```

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/test_extractor.py tests/test_updater.py tests/test_reconciler.py -v`
Expected: PASS (all — old tests unchanged because empty context is a no-op)

- [ ] **Step 5: Commit**

```bash
git add src/concierge/extractor.py src/concierge/updater.py src/concierge/reconciler.py tests/test_extractor.py tests/test_updater.py tests/test_reconciler.py
git commit -m "feat: optional reference-material context in extractor/updater/reconciler"
```

---

### Task 7: Orchestrator — typed RAG context injection

**Files:**
- Modify: `src/concierge/orchestrator.py`
- Modify: `tests/test_orchestrator.py`

**Interfaces:**
- Consumes: `types_for_module` (Task 5), `KnowledgeBase.query(..., material_types=...)` (Task 3), context kwargs (Task 6).
- Produces: `run_sync` queries knowledge once per module (extractor/updater/reconciler) with that module's type filter, query text = last 1500 chars of the batch transcript; `check_coherence` passes `material_types=types_for_module("guardian")` to its existing knowledge query. `knowledge=None` keeps context `""` everywhere.

- [ ] **Step 1: Write the failing test** — append to `tests/test_orchestrator.py`:

```python
class _SpyKnowledge:
    def __init__(self):
        self.calls = []

    def query(self, project_id, question, k=3, material_types=None):
        self.calls.append((question, tuple(material_types or ())))
        return "CTX"


def test_run_sync_queries_knowledge_per_module(fake_llm):
    import sqlite3
    from concierge.storage import Storage
    from concierge.extractor import Extractor
    from concierge.updater import CanvasUpdater
    from concierge.guardian import Guardian
    from concierge.reconciler import Reconciler
    from concierge.config import Settings

    conn = sqlite3.connect(":memory:")
    s = Storage(conn); s.init_schema()
    ex_llm = fake_llm(responses=[{"items": [
        {"type": "decision", "content": "Target SMBs", "confidence": 0.9}]}])
    up_llm = fake_llm(responses=[{"blocks": []}])
    rc_llm = fake_llm(responses=[{"transitions": []}])
    spy = _SpyKnowledge()
    settings = Settings(telegram_token="t", openai_api_key="k", batch_size=1)
    o = Orchestrator(
        storage=s, extractor=Extractor(ex_llm), updater=CanvasUpdater(up_llm),
        guardian=Guardian(llm=None), knowledge=spy, settings=settings,
        reconciler=Reconciler(rc_llm),
    )
    pid = o.ingest_message(100, "Acme", 1, "ana", "vamos focar em smbs", 1.0)
    o.run_sync(pid)
    filters = {mt for _, mt in spy.calls}
    assert ("custom_framework", "methodology") in filters          # extractor
    assert ("canvas_guide", "custom_framework") in filters         # updater
    assert ("custom_framework", "validation_guide") in filters     # reconciler
    # and the extractor actually received the context
    assert "REFERENCE MATERIAL:\nCTX" in ex_llm.calls[0][1]


def test_check_coherence_uses_guardian_filter(fake_llm):
    o = _orch_with_guardian(fake_llm(responses=[{
        "contradicts": False, "item_content": None, "reason": "ok", "confidence": 0.1,
    }]))
    spy = _SpyKnowledge()
    o.knowledge = spy
    pid = o.storage.get_or_create_project(100, "Acme")
    o.check_coherence(pid, 1, "vamos priorizar enterprise")
    assert spy.calls[0][1] == (
        "custom_framework", "generic", "methodology", "validation_guide"
    )
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_orchestrator.py -v -k "knowledge_per_module or guardian_filter"`
Expected: FAIL (`run_sync` never calls `spy.query`; `check_coherence` calls query without `material_types` → tuple mismatch)

- [ ] **Step 3: Implement** — in `src/concierge/orchestrator.py`:

3a. Add import at top:
```python
from concierge.materials import types_for_module
```

3b. In `run_sync`, after `pending` check, build the query text and a helper:
```python
    def _module_context(self, project_id, module, query_text):
        if self.knowledge is None:
            return ""
        return self.knowledge.query(
            project_id, query_text, material_types=types_for_module(module)
        )
```

3c. Wire it through `run_sync` (full updated body):
```python
    def run_sync(self, project_id):
        pending = self.storage.unprocessed_messages(project_id)
        if not pending:
            return 0
        transcript = "\n".join(f"{m['author']}: {m['text']}" for m in pending)
        qtext = transcript[-1500:]
        items = self.extractor.extract(
            pending, context=self._module_context(project_id, "extractor", qtext)
        )
        new_ids = []
        for it in items:
            new_id = self.storage.add_item(
                project_id, it.type, it.content, it.confidence,
                source_message_id=pending[0]["id"],
            )
            new_ids.append(new_id)
        if self.reconciler is not None and new_ids:
            new_items = [
                {"id": nid, "type": it.type.value, "content": it.content}
                for nid, it in zip(new_ids, items)
            ]
            prior_active = [
                i for i in self.storage.items_by_status(project_id, [ItemStatus.ACTIVE])
                if i["id"] not in set(new_ids)
            ]
            for t in self.reconciler.reconcile(
                new_items, prior_active,
                context=self._module_context(project_id, "reconciler", qtext),
            ):
                self.storage.set_item_status(t.item_id, t.new_status)
                if t.supersedes_id is not None:
                    self.storage.supersede_item(t.supersedes_id, t.item_id)
        active = self.storage.items_by_status(project_id, [ItemStatus.ACTIVE, ItemStatus.VALIDATED])
        current = self.storage.get_blocks(project_id)
        block_updates = self.updater.update(
            active, current,
            context=self._module_context(project_id, "updater", qtext),
        )
        for b in block_updates:
            self.storage.upsert_block(project_id, b.block_name, b.content, [])
        self.storage.mark_processed([m["id"] for m in pending])
        return len(new_ids)
```

3d. In `check_coherence`, change the knowledge lookup to:
```python
        context = ""
        if self.knowledge is not None:
            context = self.knowledge.query(
                project_id, text, material_types=types_for_module("guardian")
            )
```

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/test_orchestrator.py -v`
Expected: PASS (all — existing tests pass `knowledge=None`, unaffected)

- [ ] **Step 5: Full suite**

Run: `pytest -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add src/concierge/orchestrator.py tests/test_orchestrator.py
git commit -m "feat: orchestrator injects typed RAG context per module"
```

---

### Task 8: Bot — /upload, /materials, /forget drops vectors; main wiring; docs

**Files:**
- Modify: `src/concierge/bot.py`, `src/concierge/main.py`
- Modify: `tests/test_bot.py`
- Modify: `README.md`, `SETUP.md` (command tables)

**Interfaces:**
- Consumes: `MaterialService.add_material` (Task 5), `CAPABILITIES`, `MaterialError`, `Storage.list_knowledge_docs` (Task 2), `KnowledgeBase.delete` (Task 3).
- Produces (pure handlers):
  - `handle_upload_text(orchestrator, material_service, chat_id, text) -> str` — gate `/start`; empty text → usage help; else ingest and return `f"📚 Detectei: {label} → {capability}\n({chunks} trechos indexados)"`.
  - `handle_upload_document(orchestrator, material_service, chat_id, filename, data: bytes) -> str` — gate; `extract_text` errors → the `MaterialError` message; else same announcement.
  - `handle_materials(orchestrator, chat_id) -> str` — gate; empty → friendly hint; else list "📚 filename — tipo → capacidade".
  - `handle_forget` gains vector cleanup: calls `orchestrator.knowledge.delete(pid)` when `orchestrator.knowledge is not None`, before the storage delete.
  - `build_application(orchestrator, token, material_service=None)` — new optional param; registers `/upload` (command + document-with-caption), `/materials`.
  - Type labels in Portuguese: `TYPE_LABELS = {canvas_guide: "guia de canvas", validation_guide: "guia de validação", methodology: "metodologia", custom_framework: "framework próprio", generic: "material geral"}`.
- `main.py` builds `MaterialService(llm, knowledge, storage)` and passes it.

- [ ] **Step 1: Write the failing tests** — append to `tests/test_bot.py`:

```python
class _FakeMaterialService:
    def __init__(self, mtype, chunks=4, error=None):
        from concierge.models import MaterialType
        self.mtype = MaterialType(mtype)
        self.chunks = chunks
        self.error = error
        self.calls = []

    def add_material(self, project_id, filename, text):
        if self.error:
            raise self.error
        self.calls.append((project_id, filename, text))
        return self.mtype, self.chunks


class _FakeKnowledge:
    def __init__(self):
        self.deleted = []

    def delete(self, project_id):
        self.deleted.append(project_id)


def test_handle_upload_text_announces_capability(fake_llm):
    o = _orch(fake_llm)
    o.storage.get_or_create_project(100, "Acme")
    svc = _FakeMaterialService("validation_guide")
    reply = bot.handle_upload_text(o, svc, 100, "como validar hipóteses...")
    assert "guia de validação" in reply
    assert "experimentos" in reply  # capability text
    assert svc.calls[0][1] == "colado.txt"


def test_handle_upload_requires_start(fake_llm):
    o = _orch(fake_llm)
    svc = _FakeMaterialService("generic")
    assert bot.handle_upload_text(o, svc, 777, "abc") == bot.NOT_STARTED
    assert bot.handle_upload_document(o, svc, 777, "a.txt", b"x") == bot.NOT_STARTED


def test_handle_upload_document_reports_parse_error(fake_llm):
    from concierge.materials import MaterialError
    o = _orch(fake_llm)
    o.storage.get_or_create_project(100, "Acme")
    svc = _FakeMaterialService("generic")
    reply = bot.handle_upload_document(o, svc, 100, "dados.xlsx", b"bin")
    assert "não suportado" in reply.lower() or "Formato" in reply


def test_handle_materials_lists_catalog(fake_llm):
    o = _orch(fake_llm)
    pid = o.storage.get_or_create_project(100, "Acme")
    assert "nenhum material" in bot.handle_materials(o, 100).lower()
    o.storage.add_knowledge_doc(pid, "manual.pdf", "canvas_guide", 10)
    listing = bot.handle_materials(o, 100)
    assert "manual.pdf" in listing and "guia de canvas" in listing


def test_handle_forget_drops_vectors(fake_llm):
    o = _orch(fake_llm)
    pid = o.storage.get_or_create_project(100, "Acme")
    o.knowledge = _FakeKnowledge()
    bot.handle_forget(o, 100)
    assert o.knowledge.deleted == [pid]
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_bot.py -v -k "upload or materials or drops_vectors"`
Expected: FAIL with `AttributeError: module 'concierge.bot' has no attribute 'handle_upload_text'`

- [ ] **Step 3: Implement handlers** — in `src/concierge/bot.py`:

3a. Imports and labels near the top:
```python
from concierge.materials import extract_text, MaterialError, CAPABILITIES
from concierge.models import MaterialType

TYPE_LABELS = {
    MaterialType.CANVAS_GUIDE: "guia de canvas",
    MaterialType.VALIDATION_GUIDE: "guia de validação",
    MaterialType.METHODOLOGY: "metodologia",
    MaterialType.CUSTOM_FRAMEWORK: "framework próprio",
    MaterialType.GENERIC: "material geral",
}

UPLOAD_HELP = (
    "Envie um arquivo (PDF, TXT, MD, DOCX) com a legenda /upload, "
    "responda a um arquivo com /upload, ou cole o texto: /upload <texto>."
)
```

3b. Pure handlers (after `handle_sync`):
```python
def _announce(mtype, chunks):
    return (
        f"📚 Detectei: {TYPE_LABELS[mtype]} → {CAPABILITIES[mtype]}\n"
        f"({chunks} trechos indexados)"
    )


def handle_upload_text(orchestrator, material_service, chat_id, text):
    pid = orchestrator.storage.get_project(chat_id)
    if pid is None:
        return NOT_STARTED
    if not text.strip():
        return UPLOAD_HELP
    mtype, chunks = material_service.add_material(pid, "colado.txt", text)
    return _announce(mtype, chunks)


def handle_upload_document(orchestrator, material_service, chat_id, filename, data):
    pid = orchestrator.storage.get_project(chat_id)
    if pid is None:
        return NOT_STARTED
    try:
        text = extract_text(filename, data)
    except MaterialError as e:
        return f"⚠️ {e}"
    mtype, chunks = material_service.add_material(pid, filename, text)
    return _announce(mtype, chunks)


def handle_materials(orchestrator, chat_id):
    pid = orchestrator.storage.get_project(chat_id)
    if pid is None:
        return NOT_STARTED
    docs = orchestrator.storage.list_knowledge_docs(pid)
    if not docs:
        return "Nenhum material ainda. " + UPLOAD_HELP
    lines = [
        f"📚 {d['filename']} — {TYPE_LABELS[MaterialType(d['material_type'])]}"
        f" → {CAPABILITIES[MaterialType(d['material_type'])]}"
        for d in docs
    ]
    return "Materiais de referência:\n" + "\n".join(lines)
```

3c. `handle_forget` gains vector cleanup (insert before `delete_project`):
```python
def handle_forget(orchestrator, chat_id):
    pid = orchestrator.storage.get_project(chat_id)
    if pid is None:
        return NOT_STARTED
    if orchestrator.knowledge is not None:
        orchestrator.knowledge.delete(pid)
    orchestrator.storage.delete_project(pid)
    return "🗑️ Todos os dados deste projeto foram apagados."
```

3d. Async glue in `build_application` — new signature `build_application(orchestrator, token, material_service=None)` and, before the handler registrations:
```python
    MAX_UPLOAD = 20 * 1024 * 1024

    async def upload(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        chat_id = update.effective_chat.id
        if material_service is None:
            await update.message.reply_text("Upload não está configurado.")
            return
        doc = None
        if update.message.reply_to_message and update.message.reply_to_message.document:
            doc = update.message.reply_to_message.document
        if doc is not None:
            if doc.file_size and doc.file_size > MAX_UPLOAD:
                await update.message.reply_text("⚠️ Arquivo acima do limite de 20 MB.")
                return
            tg_file = await ctx.bot.get_file(doc.file_id)
            data = bytes(await tg_file.download_as_bytearray())
            reply = handle_upload_document(
                orchestrator, material_service, chat_id, doc.file_name or "arquivo", data
            )
        else:
            text = " ".join(ctx.args) if ctx.args else ""
            reply = handle_upload_text(orchestrator, material_service, chat_id, text)
        await update.message.reply_text(reply)

    async def upload_document(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        # document sent WITH caption starting with /upload
        if material_service is None:
            return
        doc = update.message.document
        if doc.file_size and doc.file_size > MAX_UPLOAD:
            await update.message.reply_text("⚠️ Arquivo acima do limite de 20 MB.")
            return
        tg_file = await ctx.bot.get_file(doc.file_id)
        data = bytes(await tg_file.download_as_bytearray())
        reply = handle_upload_document(
            orchestrator, material_service, update.effective_chat.id,
            doc.file_name or "arquivo", data,
        )
        await update.message.reply_text(reply)

    async def materials(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(
            handle_materials(orchestrator, update.effective_chat.id)
        )
```
And register (with the existing registrations):
```python
    app.add_handler(CommandHandler("upload", upload))
    app.add_handler(CommandHandler("materials", materials))
    app.add_handler(MessageHandler(
        filters.Document.ALL & filters.CaptionRegex(r"^/upload"), upload_document
    ))
```

3e. `main.py` — import and wire:
```python
from concierge.materials import MaterialService
```
and in `main()` after building `knowledge`:
```python
    material_service = MaterialService(llm, knowledge, storage)
```
and change the app line to:
```python
    app = build_application(orchestrator, settings.telegram_token, material_service)
```

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/test_bot.py -v` then `pytest -q`
Expected: all PASS.

- [ ] **Step 5: Smoke build**

Run: `PYTHONPATH=src python -c "from concierge.bot import build_application, handle_upload_text, handle_materials; import concierge.main; print('ok')"`
Expected: `ok`

- [ ] **Step 6: Update docs** — in `README.md` and `SETUP.md` command tables, add:

```
| `/upload` | (arquivo com legenda, reply a arquivo, ou texto colado) adiciona material de referência |
| `/materials` | lista os materiais ingeridos e as capacidades destravadas |
```

- [ ] **Step 7: Commit**

```bash
git add src/concierge/bot.py src/concierge/main.py tests/test_bot.py README.md SETUP.md
git commit -m "feat: /upload and /materials commands; /forget drops vectors"
```

---

## Self-Review

**Spec coverage:** §2 taxonomy/routing → T5; §3.1 materials.py → T4+T5; §3.2 models → T1, storage → T2, knowledge → T3, context params → T6, orchestrator → T7, bot/main → T8; §4 flow → T8 glue; §5 errors → T4 (MaterialError), T5 (generic fallback), T8 (size cap, friendly replies); §6 tests → embedded per task; §7 deps → T1. `/forget` chroma cleanup → T8. ✓

**Placeholders:** none — every step carries complete code. ✓

**Type consistency:** `add_material(project_id, filename, text) -> (MaterialType, int)` consistent T5/T8; `types_for_module` returns sorted list, matched by T7's tuple assertions (alphabetical: extractor=("custom_framework","methodology"), updater=("canvas_guide","custom_framework"), reconciler=("custom_framework","validation_guide"), guardian=("custom_framework","generic","methodology","validation_guide")). `ingest(..., material_type=str)` takes `.value` strings. ✓

**Known limitation (documented, not silent):** chunks ingested before this feature carry no `material_type` metadata and won't match filtered queries; acceptable — projects re-ingest via `/upload` or reset via `/forget`.
