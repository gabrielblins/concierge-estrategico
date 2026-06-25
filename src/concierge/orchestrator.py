from concierge.models import ItemType, ItemStatus


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
