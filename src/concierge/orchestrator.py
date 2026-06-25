from concierge.models import ItemStatus, ProjectMode


class Orchestrator:
    def __init__(self, storage, extractor, updater, guardian, knowledge, settings):
        self.storage = storage
        self.extractor = extractor
        self.updater = updater
        self.guardian = guardian
        self.knowledge = knowledge
        self.settings = settings

    def ingest_message(self, chat_id, chat_name, telegram_msg_id, author, text, ts):
        pid = self.storage.get_or_create_project(chat_id, chat_name)
        self.storage.add_message(pid, telegram_msg_id, author, text, ts)
        return pid

    def should_sync(self, project_id):
        pending = self.storage.unprocessed_messages(project_id)
        return len(pending) >= self.settings.batch_size

    def run_sync(self, project_id):
        pending = self.storage.unprocessed_messages(project_id)
        if not pending:
            return 0
        items = self.extractor.extract(pending)
        added = 0
        for it in items:
            self.storage.add_item(
                project_id, it.type, it.content, it.confidence,
                source_message_id=pending[0]["id"],
            )
            added += 1
        active = self.storage.items_by_status(project_id, [ItemStatus.ACTIVE])
        current = self.storage.get_blocks(project_id)
        block_updates = self.updater.update(active, current)
        for b in block_updates:
            self.storage.upsert_block(project_id, b.block_name, b.content, [])
        self.storage.mark_processed([m["id"] for m in pending])
        return added

    def check_coherence(self, project_id, message_id, text):
        if self.storage.get_mode(project_id) == ProjectMode.SILENT:
            return None
        if not self.guardian.looks_strategic(text):
            return None
        known = self.storage.items_by_status(
            project_id, [ItemStatus.VALIDATED, ItemStatus.DISCARDED]
        )
        context = ""
        if self.knowledge is not None:
            context = self.knowledge.query(project_id, text)
        verdict = self.guardian.check(text, known, context)
        if verdict is None:
            return None
        if verdict.contradicts and verdict.confidence >= self.settings.confidence_threshold:
            self.storage.add_intervention(
                project_id, message_id, None, verdict.reason, verdict.confidence
            )
            return (
                "⚠️ Atenção à coerência estratégica:\n"
                f"{verdict.reason}\n"
                f"(item relacionado: {verdict.item_content})"
            )
        return None
