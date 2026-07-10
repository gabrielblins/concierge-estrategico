import pytest
import sqlite3
from concierge.config import Settings
from concierge.storage import Storage
from concierge.extractor import Extractor
from concierge.updater import CanvasUpdater
from concierge.guardian import Guardian
from concierge.orchestrator import Orchestrator
from concierge.models import (
    ItemType, ItemStatus, ProjectMode, ExtractionResult, CanvasUpdateResult,
    CoherenceVerdict, Contribution,
)


@pytest.fixture
def orch(fake_executor):
    conn = sqlite3.connect(":memory:")
    s = Storage(conn); s.init_schema()
    extractor_ex = fake_executor(results=[ExtractionResult.model_validate({
        "items": [{"type": "decision", "content": "Target SMBs", "confidence": 0.9}]
    })])
    updater_ex = fake_executor(results=[CanvasUpdateResult.model_validate({
        "blocks": [{"block_name": "customer_segments", "content": "SMBs"}]
    })])
    settings = Settings(telegram_token="t", openai_api_key="k", batch_size=2)
    return Orchestrator(
        storage=s,
        extractor=Extractor(extractor_ex),
        updater=CanvasUpdater(updater_ex),
        guardian=Guardian(None),
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


def _orch_with_guardian(guardian_executor):
    conn = sqlite3.connect(":memory:")
    s = Storage(conn); s.init_schema()
    settings = Settings(telegram_token="t", openai_api_key="k", confidence_threshold=0.75)
    return Orchestrator(
        storage=s, extractor=None, updater=None,
        guardian=Guardian(guardian_executor), knowledge=None, settings=settings,
    )


def test_check_silent_on_trivial_message(fake_executor):
    o = _orch_with_guardian(fake_executor(results=[]))
    pid = o.storage.get_or_create_project(100, "Acme")
    assert o.check_coherence(pid, None, "kkk ok") is None
    # no executor call was made (prefilter blocked it)
    assert o.guardian.executor.calls == []


def test_check_alerts_on_high_confidence_contradiction(fake_executor):
    o = _orch_with_guardian(fake_executor(results=[CoherenceVerdict(
        contradicts=True,
        item_content="Validated SMB focus",
        reason="proposes enterprise",
        confidence=0.9,
    )]))
    pid = o.storage.get_or_create_project(100, "Acme")
    o.storage.add_item(pid, ItemType.HYPOTHESIS, "Validated SMB focus", 0.9, None,
                       status=ItemStatus.VALIDATED)
    alert = o.check_coherence(pid, 1, "vamos priorizar enterprise agora")
    assert alert is not None
    assert "enterprise" in alert.lower() or "SMB" in alert
    assert o.storage.last_intervention(pid)["confidence"] == 0.9


def test_check_silent_below_threshold(fake_executor):
    o = _orch_with_guardian(fake_executor(results=[CoherenceVerdict(
        contradicts=True, item_content="x", reason="maybe", confidence=0.5,
    )]))
    pid = o.storage.get_or_create_project(100, "Acme")
    assert o.check_coherence(pid, 1, "vamos mudar o foco") is None


def test_run_sync_applies_reconciliation(fake_executor):
    import sqlite3
    from concierge.storage import Storage
    from concierge.extractor import Extractor
    from concierge.updater import CanvasUpdater
    from concierge.guardian import Guardian
    from concierge.reconciler import Reconciler
    from concierge.config import Settings
    from concierge.models import (
        ItemStatus, ExtractionResult, CanvasUpdateResult, ReconciliationResult,
    )

    conn = sqlite3.connect(":memory:")
    s = Storage(conn); s.init_schema()
    extractor_ex = fake_executor(results=[ExtractionResult.model_validate({
        "items": [{"type": "hypothesis", "content": "SMBs will pay", "confidence": 0.9}]
    })])
    updater_ex = fake_executor(results=[CanvasUpdateResult.model_validate({"blocks": []})])
    reconciler_ex = fake_executor(results=[ReconciliationResult.model_validate({
        "transitions": [{"item_id": 1, "new_status": "validated", "supersedes_id": None}]
    })])
    settings = Settings(telegram_token="t", openai_api_key="k", batch_size=1)
    o = Orchestrator(
        storage=s, extractor=Extractor(extractor_ex), updater=CanvasUpdater(updater_ex),
        guardian=Guardian(None), knowledge=None, settings=settings,
        reconciler=Reconciler(reconciler_ex),
    )
    pid = o.ingest_message(100, "Acme", 1, "ana", "smbs will pay", 1.0)
    o.run_sync(pid)
    validated = o.storage.items_by_status(pid, [ItemStatus.VALIDATED])
    assert len(validated) == 1
    assert validated[0]["content"] == "SMBs will pay"


def test_check_silent_when_mode_silent(fake_executor):
    o = _orch_with_guardian(fake_executor(results=[]))
    pid = o.storage.get_or_create_project(100, "Acme")
    o.storage.set_mode(pid, ProjectMode.SILENT)
    assert o.check_coherence(pid, 1, "vamos priorizar enterprise") is None


def test_run_sync_builds_canvas_from_validated_items(fake_executor):
    import sqlite3
    from concierge.storage import Storage
    from concierge.extractor import Extractor
    from concierge.updater import CanvasUpdater
    from concierge.guardian import Guardian
    from concierge.reconciler import Reconciler
    from concierge.config import Settings
    from concierge.models import (
        ItemStatus, ExtractionResult, CanvasUpdateResult, ReconciliationResult,
    )

    conn = sqlite3.connect(":memory:")
    s = Storage(conn); s.init_schema()
    extractor_ex = fake_executor(results=[ExtractionResult.model_validate({
        "items": [{"type": "decision", "content": "Target SMBs", "confidence": 0.9}]
    })])
    # The updater fake will only return a block if it actually received the item.
    # We assert on the call it received, proving the item list was non-empty.
    updater_ex = fake_executor(results=[CanvasUpdateResult.model_validate({
        "blocks": [{"block_name": "customer_segments", "content": "SMBs"}]
    })])
    reconciler_ex = fake_executor(results=[ReconciliationResult.model_validate({
        "transitions": [{"item_id": 1, "new_status": "validated", "supersedes_id": None}]
    })])
    settings = Settings(telegram_token="t", openai_api_key="k", batch_size=1)
    o = Orchestrator(
        storage=s, extractor=Extractor(extractor_ex), updater=CanvasUpdater(updater_ex),
        guardian=Guardian(None), knowledge=None, settings=settings,
        reconciler=Reconciler(reconciler_ex),
    )
    pid = o.ingest_message(100, "Acme", 1, "ana", "vamos focar em smbs", 1.0)
    o.run_sync(pid)

    # The item was promoted to VALIDATED by the reconciler...
    assert len(s.items_by_status(pid, [ItemStatus.VALIDATED])) == 1
    # ...and the canvas updater STILL received it (its user prompt must mention the item),
    # so a block was written rather than an empty canvas.
    updater_call = updater_ex.calls[0]  # (agent, user, schema)
    assert "Target SMBs" in updater_call[1]
    blocks = s.get_blocks(pid)
    assert any(b["block_name"] == "customer_segments" for b in blocks)


class _SpyKnowledge:
    def __init__(self):
        self.calls = []

    def query(self, project_id, question, k=3, material_types=None):
        self.calls.append((question, tuple(material_types or ())))
        return "CTX"


def test_run_sync_queries_knowledge_per_module(fake_executor):
    import sqlite3
    from concierge.storage import Storage
    from concierge.extractor import Extractor
    from concierge.updater import CanvasUpdater
    from concierge.guardian import Guardian
    from concierge.reconciler import Reconciler
    from concierge.config import Settings
    from concierge.models import ExtractionResult, CanvasUpdateResult, ReconciliationResult

    conn = sqlite3.connect(":memory:")
    s = Storage(conn); s.init_schema()
    ex_ex = fake_executor(results=[ExtractionResult.model_validate({"items": [
        {"type": "decision", "content": "Target SMBs", "confidence": 0.9}]})])
    up_ex = fake_executor(results=[CanvasUpdateResult.model_validate({"blocks": []})])
    rc_ex = fake_executor(results=[ReconciliationResult.model_validate({"transitions": []})])
    spy = _SpyKnowledge()
    settings = Settings(telegram_token="t", openai_api_key="k", batch_size=1)
    o = Orchestrator(
        storage=s, extractor=Extractor(ex_ex), updater=CanvasUpdater(up_ex),
        guardian=Guardian(None), knowledge=spy, settings=settings,
        reconciler=Reconciler(rc_ex),
    )
    pid = o.ingest_message(100, "Acme", 1, "ana", "vamos focar em smbs", 1.0)
    o.run_sync(pid)
    filters = {mt for _, mt in spy.calls}
    assert ("custom_framework", "methodology") in filters          # extractor
    assert ("canvas_guide", "custom_framework") in filters         # updater
    assert ("custom_framework", "validation_guide") in filters     # reconciler
    # and the extractor actually received the context
    assert "REFERENCE MATERIAL:\nCTX" in ex_ex.calls[0][1]


def test_check_coherence_uses_guardian_filter(fake_executor):
    o = _orch_with_guardian(fake_executor(results=[CoherenceVerdict(
        contradicts=False, item_content=None, reason="ok", confidence=0.1,
    )]))
    spy = _SpyKnowledge()
    o.knowledge = spy
    pid = o.storage.get_or_create_project(100, "Acme")
    o.check_coherence(pid, 1, "vamos priorizar enterprise")
    assert spy.calls[0][1] == (
        "custom_framework", "generic", "methodology", "validation_guide"
    )


def test_check_coherence_passes_personality_as_style(fake_executor):
    guardian_ex = fake_executor(results=[CoherenceVerdict(
        contradicts=False, item_content=None, reason="ok", confidence=0.1,
    )])
    o = _orch_with_guardian(guardian_ex)
    pid = o.storage.get_or_create_project(100, "Acme")
    o.storage.set_personality(pid, "fale como um mentor direto")
    o.check_coherence(pid, 1, "vamos priorizar enterprise")
    assert "fale como um mentor direto" in guardian_ex.calls[0][1]


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


def _orch_with_participant(fake_executor, participant, **settings_kw):
    conn = sqlite3.connect(":memory:")
    s = Storage(conn); s.init_schema()
    kw = dict(telegram_token="t", openai_api_key="k",
              participation_cooldown=2, participation_threshold=0.75)
    kw.update(settings_kw)
    settings = Settings(**kw)
    return Orchestrator(
        storage=s, extractor=None, updater=None,
        guardian=Guardian(None), knowledge=None, settings=settings,
        participant=participant,
    )


def _seed(o, n):
    pid = o.storage.get_or_create_project(100, "Acme")
    for i in range(1, n + 1):
        o.storage.add_message(pid, i, "ana", f"vamos priorizar o segmento {i}", float(i))
    return pid


def test_participate_gates_before_llm(fake_executor):
    from concierge.models import Contribution, ProjectMode
    good = Contribution(should_contribute=True, relevance=0.9,
                        kind="question", text="E a evidência?")
    # enabled=False
    p = _FakeParticipant(contribution=good)
    o = _orch_with_participant(fake_executor, p, participation_enabled=False)
    pid = _seed(o, 3)
    assert o.participate(pid, 3, "vamos priorizar enterprise") is None
    # silent mode
    p2 = _FakeParticipant(contribution=good)
    o2 = _orch_with_participant(fake_executor, p2)
    pid2 = _seed(o2, 3)
    o2.storage.set_mode(pid2, ProjectMode.SILENT)
    assert o2.participate(pid2, 3, "vamos priorizar enterprise") is None
    # cooldown not elapsed (cooldown=2; only 1 message since marker)
    p3 = _FakeParticipant(contribution=good)
    o3 = _orch_with_participant(fake_executor, p3)
    pid3 = _seed(o3, 3)
    o3.storage.set_last_participation(pid3, 2)
    assert o3.participate(pid3, 3, "vamos priorizar enterprise") is None
    # prefilter: trivial text
    p4 = _FakeParticipant(contribution=good)
    o4 = _orch_with_participant(fake_executor, p4)
    pid4 = _seed(o4, 3)
    assert o4.participate(pid4, 3, "kkk ok") is None
    # none of the gated cases reached the LLM stage
    assert p.consider_calls == p2.consider_calls == p3.consider_calls == p4.consider_calls == []


def test_participate_threshold_and_success_updates_cooldown(fake_executor):
    from concierge.models import Contribution
    weak = Contribution(should_contribute=True, relevance=0.5, kind="question", text="?")
    p = _FakeParticipant(contribution=weak)
    o = _orch_with_participant(fake_executor, p)
    pid = _seed(o, 3)
    assert o.participate(pid, 3, "vamos priorizar o segmento enterprise") is None
    strong = Contribution(should_contribute=True, relevance=0.9,
                          kind="connection", text="Isso liga com a hipótese X.")
    p2 = _FakeParticipant(contribution=strong)
    o2 = _orch_with_participant(fake_executor, p2)
    pid2 = _seed(o2, 3)
    out = o2.participate(pid2, 3, "vamos priorizar o segmento enterprise")
    assert out == "Isso liga com a hipótese X."
    assert o2.storage.get_last_participation(pid2) == 3
    # window and personality were assembled
    window, items, materials, style = p2.consider_calls[0]
    assert len(window) == 3 and materials == ""


def test_respond_mention_no_gates_and_style(fake_executor):
    p = _FakeParticipant(reply="Na minha visão, testem com 5 clientes.")
    o = _orch_with_participant(fake_executor, p, participation_enabled=False)
    pid = _seed(o, 2)
    o.storage.set_personality(pid, "voz de mentor")
    out = o.respond_mention(pid, 2, "bot, o que acha?")
    assert out == "Na minha visão, testem com 5 clientes."
    _, _, _, mention, style = p.respond_calls[0]
    assert mention == "bot, o que acha?" and style == "voz de mentor"


def test_participate_none_participant_is_silent(fake_executor):
    o = _orch_with_participant(fake_executor, None)
    pid = _seed(o, 3)
    assert o.participate(pid, 3, "vamos priorizar enterprise") is None
    assert o.respond_mention(pid, 3, "bot?") is None


def test_participate_cooldown_survives_divergent_telegram_ids(fake_executor):
    from concierge.models import Contribution
    strong = Contribution(should_contribute=True, relevance=0.9,
                          kind="connection", text="Liga com a hipótese X.")
    p = _FakeParticipant(contribution=strong)
    o = _orch_with_participant(fake_executor, p)  # cooldown=2
    pid = o.storage.get_or_create_project(100, "Acme")
    # Telegram ids diverge from row ids (offset +1000), like production
    for i in range(1, 4):
        o.storage.add_message(pid, 1000 + i, "ana", f"vamos priorizar o segmento {i}", float(i))
    out = o.participate(pid, 1003, "vamos priorizar o segmento enterprise")
    assert out == "Liga com a hipótese X."
    # marker must be a ROW id (small), not the telegram id (1000+)
    assert o.storage.get_last_participation(pid) <= 3
    # two more messages arrive -> cooldown (2) elapses -> allowed to contribute again
    o.storage.add_message(pid, 1004, "bob", "vamos priorizar o segmento saude", 4.0)
    o.storage.add_message(pid, 1005, "ana", "vamos priorizar o segmento educacao", 5.0)
    p.contribution = strong
    out2 = o.participate(pid, 1005, "vamos priorizar o segmento educacao")
    assert out2 == "Liga com a hipótese X."
