from concierge.models import ExtractionResult

SYSTEM = (
    "You extract strategic items from a startup team's chat. "
    "Return JSON {\"items\": [{\"type\": one of "
    "decision|hypothesis|premise|risk|task|learning, "
    "\"content\": short statement, \"confidence\": 0..1}]}. "
    "Only include substantive strategic content; skip small talk."
)


class Extractor:
    def __init__(self, executor, agent=None):
        self.executor = executor
        self.agent = agent

    def extract(self, messages, context=""):
        transcript = "\n".join(f"{m['author']}: {m['text']}" for m in messages)
        if context:
            transcript += f"\n\nREFERENCE MATERIAL:\n{context}"
        result = self.executor.run_validated(
            self.agent, transcript, ExtractionResult
        )
        if result is None:
            return []
        return result.items
