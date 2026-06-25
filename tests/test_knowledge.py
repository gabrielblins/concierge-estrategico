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
