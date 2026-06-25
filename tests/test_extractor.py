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
