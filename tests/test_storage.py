from concierge.models import ProjectMode


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
