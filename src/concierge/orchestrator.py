from concierge.models import ItemStatus, ProjectMode
from concierge.materials import types_for_module


class Orchestrator:
    def __init__(self, storage, extractor, updater, guardian, knowledge, settings, reconciler=None):
        self.storage = storage
        self.extractor = extractor
        self.updater = updater
        self.guardian = guardian
        self.knowledge = knowledge
        self.settings = settings
        self.reconciler = reconciler

    def ingest_message(self, chat_id, chat_name, telegram_msg_id, author, text, ts):
        pid = self.storage.get_or_create_project(chat_id, chat_name)
        self.storage.add_message(pid, telegram_msg_id, author, text, ts)
        return pid

    def should_sync(self, project_id):
        pending = self.storage.unprocessed_messages(project_id)
        return len(pending) >= self.settings.batch_size

    def _module_context(self, project_id, module, query_text):
        if self.knowledge is None:
            return ""
        return self.knowledge.query(
            project_id, query_text, material_types=types_for_module(module)
        )

    def run_sync(self, project_id):
        pending = self.storage.unprocessed_messages(project_id)
        if not pending:
            return 0
        transcript = "\n".join(f"{m['author']}: {m['text']}" for m in pending)
        qtext = transcript[-1500:]
        items = self.extractor.extract(
            pending, context=self._module_context(project_id, "extractor", qtext)
        )
        new_ids = []
        for it in items:
            new_id = self.storage.add_item(
                project_id, it.type, it.content, it.confidence,
                source_message_id=pending[0]["id"],
            )
            new_ids.append(new_id)
        if self.reconciler is not None and new_ids:
            new_items = [
                {"id": nid, "type": it.type.value, "content": it.content}
                for nid, it in zip(new_ids, items)
            ]
            prior_active = [
                i for i in self.storage.items_by_status(project_id, [ItemStatus.ACTIVE])
                if i["id"] not in set(new_ids)
            ]
            for t in self.reconciler.reconcile(
                new_items, prior_active,
                context=self._module_context(project_id, "reconciler", qtext),
            ):
                self.storage.set_item_status(t.item_id, t.new_status)
                if t.supersedes_id is not None:
                    self.storage.supersede_item(t.supersedes_id, t.item_id)
        active = self.storage.items_by_status(project_id, [ItemStatus.ACTIVE, ItemStatus.VALIDATED])
        current = self.storage.get_blocks(project_id)
        block_updates = self.updater.update(
            active, current,
            context=self._module_context(project_id, "updater", qtext),
        )
        for b in block_updates:
            self.storage.upsert_block(project_id, b.block_name, b.content, [])
        self.storage.mark_processed([m["id"] for m in pending])
        return len(new_ids)

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
            context = self.knowledge.query(
                project_id, text, material_types=types_for_module("guardian")
            )
        style = self.storage.get_personality(project_id)
        verdict = self.guardian.check(text, known, context, style=style)
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
