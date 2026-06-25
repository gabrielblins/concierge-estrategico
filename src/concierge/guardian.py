from concierge.llm.client import call_validated
from concierge.models import CoherenceVerdict

SIGNALS = [
    "decid", "vamos", "proposta", "proponho", "mudar", "priorizar",
    "foco", "estratégia", "hipótese", "descartar", "pivot", "target", "segmento",
]

SYSTEM = (
    "You are a strategic coherence guardian for a startup team. "
    "Given a new message, the team's validated/discarded strategic items, "
    "and optional method context, decide whether the message contradicts "
    "established strategy. Return JSON "
    "{\"contradicts\": bool, \"item_content\": the conflicting item or null, "
    "\"reason\": short explanation, \"confidence\": 0..1}."
)


class Guardian:
    def __init__(self, llm):
        self.llm = llm

    def looks_strategic(self, text: str) -> bool:
        low = text.lower()
        return any(sig in low for sig in SIGNALS)

    def check(self, text, known_items, method_context=""):
        items_txt = "\n".join(f"[{i['type']}] {i['content']}" for i in known_items)
        user = (
            f"NEW MESSAGE:\n{text}\n\n"
            f"KNOWN ITEMS:\n{items_txt}\n\n"
            f"METHOD CONTEXT:\n{method_context}"
        )
        return call_validated(self.llm, SYSTEM, user, CoherenceVerdict)
