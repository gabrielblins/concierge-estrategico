from concierge.models import ItemStatus, ProjectMode
from concierge.materials import types_for_module


class Orchestrator:
    def __init__(self, storage, extractor, updater, guardian, knowledge, settings, reconciler=None, participant=None):
        self.storage = storage
        self.extractor = extractor
        self.updater = updater
        self.guardian = guardian
        self.knowledge = knowledge
        self.settings = settings
        self.reconciler = reconciler
        self.participant = participant

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

    def _funnel(self):
        if getattr(self, "_funnel_agent", None) is None:
            from concierge.agents.funnel import MessageFunnelAgent

            self._funnel_agent = MessageFunnelAgent(
                name="message_funnel",
                guardian_facade=self.guardian,
                participant_facade=self.participant,
                confidence_threshold=self.settings.confidence_threshold,
                participation_threshold=self.settings.participation_threshold,
            )
        return self._funnel_agent

    def _run_funnel(self, project_id, message_id, text):
        key = (project_id, message_id)
        cached = getattr(self, "_last_funnel", None)
        if cached and cached[0] == key:
            return cached[1]
        silent = self.storage.get_mode(project_id) == ProjectMode.SILENT
        if silent or not self.guardian.looks_strategic(text):
            result = {"decision": "none"}
            self._last_funnel = (key, result)
            return result
        gates = {
            "silent": False,
            "participation_ok": self._participation_ok(project_id, text),
        }
        known = self.storage.items_by_status(
            project_id, [ItemStatus.VALIDATED, ItemStatus.DISCARDED]
        )
        window, items, materials_p, style = self._participant_context(
            project_id, text
        )
        materials_g = ""
        if self.knowledge is not None:
            materials_g = self.knowledge.query(
                project_id, text, material_types=types_for_module("guardian")
            )
        result = self._funnel().decide(
            gates=gates, text=text, known_items=known, window=window,
            items=items, materials_guardian=materials_g,
            materials_participant=materials_p, style=style,
        )
        self._last_funnel = (key, result)
        return result

    def _participation_ok(self, project_id, text):
        if self.participant is None or not self.settings.participation_enabled:
            return False
        marker = self.storage.get_last_participation(project_id)
        if (marker is not None and
                self.storage.messages_since(project_id, marker)
                < self.settings.participation_cooldown):
            return False
        return len(text) >= 20

    def check_coherence(self, project_id, message_id, text):
        result = self._run_funnel(project_id, message_id, text)
        if result["decision"] != "alert":
            return None
        self.storage.add_intervention(
            project_id, message_id, None, result["reason"], result["confidence"]
        )
        return (
            "⚠️ Atenção à coerência estratégica:\n"
            f"{result['reason']}\n"
            f"(item relacionado: {result['item_content']})"
        )

    def _participant_context(self, project_id, text):
        window = self.storage.recent_messages(project_id, 15)
        items = self.storage.items_by_status(
            project_id, [ItemStatus.ACTIVE, ItemStatus.VALIDATED]
        )
        materials = ""
        if self.knowledge is not None:
            materials = self.knowledge.query(
                project_id, text, material_types=types_for_module("participant")
            )
        style = self.storage.get_personality(project_id)
        return window, items, materials, style

    def participate(self, project_id, message_id, text):
        result = self._run_funnel(project_id, message_id, text)
        if result["decision"] != "contribution":
            return None
        window = self.storage.recent_messages(project_id, 1)
        if window:
            self.storage.set_last_participation(project_id, window[-1]["id"])
        return result["text"]

    def respond_mention(self, project_id, message_id, text):
        if self.participant is None:
            return None
        window, items, materials, style = self._participant_context(project_id, text)
        return self.participant.respond(window, items, materials, text, style=style)
