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
    # forget deleted the project; re-create it explicitly to confirm it's empty
    pid2 = o.storage.get_or_create_project(100, "Acme")
    assert o.storage.items_by_status(pid2, [ItemStatus.ACTIVE]) == []


def test_handle_sync_returns_confirmation(fake_llm):
    o = _orch(fake_llm)
    o.storage.get_or_create_project(100, "Acme")
    reply = bot.handle_sync(o, chat_id=100)
    assert "sync" in reply.lower()


def test_handlers_require_start(fake_llm):
    o = _orch(fake_llm)
    # no project created for chat 777
    assert bot.handle_status(o, 777) == bot.NOT_STARTED
    assert bot.handle_why(o, 777) == bot.NOT_STARTED
    assert bot.handle_forget(o, 777) == bot.NOT_STARTED
    assert bot.handle_sync(o, 777) == bot.NOT_STARTED


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


def test_is_mention_detection():
    assert bot._is_mention("valeu @meu_bot, o que acha?", "meu_bot", False) is True
    assert bot._is_mention("valeu @Meu_Bot!", "meu_bot", False) is True
    assert bot._is_mention("qualquer texto", "meu_bot", True) is True
    assert bot._is_mention("sem mencao aqui", "meu_bot", False) is False
    assert bot._is_mention("@outro_bot oi", "meu_bot", False) is False
    assert bot._is_mention("@meu_bot oi", None, False) is False
