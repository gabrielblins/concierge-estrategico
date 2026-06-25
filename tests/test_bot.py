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
