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
