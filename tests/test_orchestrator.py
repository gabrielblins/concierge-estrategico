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
