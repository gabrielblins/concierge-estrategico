import pytest
import sqlite3
from concierge.config import Settings
from concierge.storage import Storage
from concierge.extractor import Extractor
from concierge.updater import CanvasUpdater
from concierge.guardian import Guardian
from concierge.orchestrator import Orchestrator
from concierge.models import ItemType, ItemStatus, ProjectMode


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
    assert items[0]["source_message_id"] is not None
    blocks = orch.storage.get_blocks(pid)
    assert blocks[0]["block_name"] == "customer_segments"
    # messages now processed
    assert orch.storage.unprocessed_messages(pid) == []


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


def test_run_sync_applies_reconciliation(fake_llm):
    import sqlite3
    from concierge.storage import Storage
    from concierge.extractor import Extractor
    from concierge.updater import CanvasUpdater
    from concierge.guardian import Guardian
    from concierge.reconciler import Reconciler
    from concierge.config import Settings
    from concierge.models import ItemStatus

    conn = sqlite3.connect(":memory:")
    s = Storage(conn); s.init_schema()
    extractor_llm = fake_llm(responses=[{
        "items": [{"type": "hypothesis", "content": "SMBs will pay", "confidence": 0.9}]
    }])
    updater_llm = fake_llm(responses=[{"blocks": []}])
    reconciler_llm = fake_llm(responses=[{
        "transitions": [{"item_id": 1, "new_status": "validated", "supersedes_id": None}]
    }])
    settings = Settings(telegram_token="t", openai_api_key="k", batch_size=1)
    o = Orchestrator(
        storage=s, extractor=Extractor(extractor_llm), updater=CanvasUpdater(updater_llm),
        guardian=Guardian(llm=None), knowledge=None, settings=settings,
        reconciler=Reconciler(reconciler_llm),
    )
    pid = o.ingest_message(100, "Acme", 1, "ana", "smbs will pay", 1.0)
    o.run_sync(pid)
    validated = o.storage.items_by_status(pid, [ItemStatus.VALIDATED])
    assert len(validated) == 1
    assert validated[0]["content"] == "SMBs will pay"


def test_check_silent_when_mode_silent(fake_llm):
    o = _orch_with_guardian(fake_llm(responses=[]))
    pid = o.storage.get_or_create_project(100, "Acme")
    o.storage.set_mode(pid, ProjectMode.SILENT)
    assert o.check_coherence(pid, 1, "vamos priorizar enterprise") is None


def test_run_sync_builds_canvas_from_validated_items(fake_llm):
    import sqlite3
    from concierge.storage import Storage
    from concierge.extractor import Extractor
    from concierge.updater import CanvasUpdater
    from concierge.guardian import Guardian
    from concierge.reconciler import Reconciler
    from concierge.config import Settings
    from concierge.models import ItemStatus

    conn = sqlite3.connect(":memory:")
    s = Storage(conn); s.init_schema()
    extractor_llm = fake_llm(responses=[{
        "items": [{"type": "decision", "content": "Target SMBs", "confidence": 0.9}]
    }])
    # The updater fake will only return a block if it actually received the item.
    # We assert on the call it received, proving the item list was non-empty.
    updater_llm = fake_llm(responses=[{
        "blocks": [{"block_name": "customer_segments", "content": "SMBs"}]
    }])
    reconciler_llm = fake_llm(responses=[{
        "transitions": [{"item_id": 1, "new_status": "validated", "supersedes_id": None}]
    }])
    settings = Settings(telegram_token="t", openai_api_key="k", batch_size=1)
    o = Orchestrator(
        storage=s, extractor=Extractor(extractor_llm), updater=CanvasUpdater(updater_llm),
        guardian=Guardian(llm=None), knowledge=None, settings=settings,
        reconciler=Reconciler(reconciler_llm),
    )
    pid = o.ingest_message(100, "Acme", 1, "ana", "vamos focar em smbs", 1.0)
    o.run_sync(pid)

    # The item was promoted to VALIDATED by the reconciler...
    assert len(s.items_by_status(pid, [ItemStatus.VALIDATED])) == 1
    # ...and the canvas updater STILL received it (its user prompt must mention the item),
    # so a block was written rather than an empty canvas.
    updater_call = updater_llm.calls[0]  # (system, user)
    assert "Target SMBs" in updater_call[1]
    blocks = s.get_blocks(pid)
    assert any(b["block_name"] == "customer_segments" for b in blocks)


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
