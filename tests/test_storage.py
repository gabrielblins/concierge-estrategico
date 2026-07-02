from concierge.models import ProjectMode, ItemType, ItemStatus


def test_get_or_create_project_is_idempotent(storage):
    p1 = storage.get_or_create_project(chat_id=100, name="Acme")
    p2 = storage.get_or_create_project(chat_id=100, name="Acme")
    assert p1 == p2


def test_add_message_dedupes_on_telegram_id(storage):
    pid = storage.get_or_create_project(100, "Acme")
    first = storage.add_message(pid, telegram_msg_id=5, author="ana", text="hi", ts=1.0)
    dup = storage.add_message(pid, telegram_msg_id=5, author="ana", text="hi", ts=1.0)
    assert first is not None
    assert dup is None


def test_unprocessed_then_mark_processed(storage):
    pid = storage.get_or_create_project(100, "Acme")
    mid = storage.add_message(pid, 5, "ana", "we will target SMBs", 1.0)
    assert len(storage.unprocessed_messages(pid)) == 1
    storage.mark_processed([mid])
    assert storage.unprocessed_messages(pid) == []


def test_mode_defaults_to_moderate_and_can_change(storage):
    pid = storage.get_or_create_project(100, "Acme")
    assert storage.get_mode(pid) == ProjectMode.MODERATE
    storage.set_mode(pid, ProjectMode.SILENT)
    assert storage.get_mode(pid) == ProjectMode.SILENT


def test_add_and_query_items_by_status(storage):
    pid = storage.get_or_create_project(100, "Acme")
    i1 = storage.add_item(pid, ItemType.HYPOTHESIS, "SMBs will pay", 0.8, None)
    storage.set_item_status(i1, ItemStatus.VALIDATED)
    validated = storage.items_by_status(pid, [ItemStatus.VALIDATED])
    assert len(validated) == 1
    assert validated[0]["content"] == "SMBs will pay"


def test_supersede_marks_old_item(storage):
    pid = storage.get_or_create_project(100, "Acme")
    old = storage.add_item(pid, ItemType.DECISION, "target enterprise", 0.7, None)
    new = storage.add_item(pid, ItemType.DECISION, "target SMBs", 0.9, None)
    storage.supersede_item(old, new)
    superseded = storage.items_by_status(pid, [ItemStatus.SUPERSEDED])
    assert superseded[0]["id"] == old


def test_intervention_roundtrip(storage):
    pid = storage.get_or_create_project(100, "Acme")
    storage.add_intervention(pid, message_id=3, item_id=7, reason="conflicts with X", confidence=0.9)
    last = storage.last_intervention(pid)
    assert last["reason"] == "conflicts with X"
    assert last["item_id"] == 7


def test_get_project_returns_none_when_absent_and_id_when_present(storage):
    assert storage.get_project(555) is None
    pid = storage.get_or_create_project(555, "Acme")
    assert storage.get_project(555) == pid


def test_upsert_and_get_block(storage):
    pid = storage.get_or_create_project(100, "Acme")
    storage.upsert_block(pid, "value_proposition", "Save time on X", [1, 2])
    storage.upsert_block(pid, "value_proposition", "Save time and money on X", [1, 2, 3])
    blocks = storage.get_blocks(pid)
    assert len(blocks) == 1
    assert blocks[0]["content"] == "Save time and money on X"
    assert blocks[0]["source_items"] == [1, 2, 3]


def test_knowledge_doc_roundtrip_with_type(storage):
    pid = storage.get_or_create_project(100, "Acme")
    storage.add_knowledge_doc(pid, "manual-bmc.pdf", "canvas_guide", 12)
    storage.add_knowledge_doc(pid, "notas.txt", "generic", 3)
    docs = storage.list_knowledge_docs(pid)
    assert len(docs) == 2
    assert docs[0]["filename"] == "manual-bmc.pdf"
    assert docs[0]["material_type"] == "canvas_guide"
    assert docs[0]["chunk_count"] == 12


def test_personality_roundtrip_and_default(storage):
    pid = storage.get_or_create_project(100, "Acme")
    assert storage.get_personality(pid) == ""
    storage.set_personality(pid, "fale como um mentor direto")
    assert storage.get_personality(pid) == "fale como um mentor direto"
    storage.set_personality(pid, "")
    assert storage.get_personality(pid) == ""


def test_recent_messages_window_oldest_to_newest(storage):
    pid = storage.get_or_create_project(100, "Acme")
    for i in range(1, 6):
        storage.add_message(pid, i, "ana", f"msg {i}", float(i))
    window = storage.recent_messages(pid, limit=3)
    assert [m["text"] for m in window] == ["msg 3", "msg 4", "msg 5"]
    assert set(window[0]) == {"id", "author", "text"}


def test_participation_cooldown_roundtrip(storage):
    pid = storage.get_or_create_project(100, "Acme")
    assert storage.get_last_participation(pid) is None
    m1 = storage.add_message(pid, 1, "ana", "a", 1.0)
    m2 = storage.add_message(pid, 2, "ana", "b", 2.0)
    m3 = storage.add_message(pid, 3, "ana", "c", 3.0)
    assert storage.messages_since(pid, None) == 3
    storage.set_last_participation(pid, m1)
    assert storage.get_last_participation(pid) == m1
    assert storage.messages_since(pid, m1) == 2
    assert storage.messages_since(pid, m3) == 0


def test_get_project_name_and_canvas_updated_at(storage):
    assert storage.get_project_name(999) == ""
    pid = storage.get_or_create_project(100, "Acme")
    assert storage.get_project_name(pid) == "Acme"
    assert storage.canvas_updated_at(pid) is None
    storage.upsert_block(pid, "customer_segments", "SMBs", [1])
    ts = storage.canvas_updated_at(pid)
    assert isinstance(ts, float) and ts > 0
