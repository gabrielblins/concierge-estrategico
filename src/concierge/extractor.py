from concierge.llm.client import call_validated
from concierge.models import ExtractionResult

SYSTEM = (
    "You extract strategic items from a startup team's chat. "
    "Return JSON {\"items\": [{\"type\": one of "
    "decision|hypothesis|premise|risk|task|learning, "
    "\"content\": short statement, \"confidence\": 0..1}]}. "
    "Only include substantive strategic content; skip small talk."
)


class Extractor:
    def __init__(self, llm):
        self.llm = llm

    def extract(self, messages):
        transcript = "\n".join(f"{m['author']}: {m['text']}" for m in messages)
        result = call_validated(self.llm, SYSTEM, transcript, ExtractionResult)
        if result is None:
            return []
        return result.items
