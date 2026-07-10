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
    def __init__(self, executor, agent=None):
        self.executor = executor
        self.agent = agent

    def looks_strategic(self, text: str) -> bool:
        low = text.lower()
        return any(sig in low for sig in SIGNALS)

    def check(self, text, known_items, method_context="", style=""):
        items_txt = "\n".join(f"[{i['type']}] {i['content']}" for i in known_items)
        user = (
            f"NEW MESSAGE:\n{text}\n\n"
            f"KNOWN ITEMS:\n{items_txt}\n\n"
            f"METHOD CONTEXT:\n{method_context}"
        )
        if style:
            user += f"\n\nWrite the 'reason' field in this voice: {style}"
        return self.executor.run_validated(self.agent, user, CoherenceVerdict)
