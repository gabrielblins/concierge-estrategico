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
