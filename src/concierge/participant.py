import json

from concierge.models import Contribution, StyledText


def _unwrap_text(text):
    """Defensively unwrap a double-encoded {"text": "..."} payload."""
    candidate = (text or "").strip()
    if candidate.startswith("{"):
        try:
            inner = json.loads(candidate)
        except (ValueError, TypeError):
            return text
        if isinstance(inner, dict) and isinstance(inner.get("text"), str):
            return inner["text"]
    return text

CONSIDER_SYSTEM = (
    "You are a thoughtful member of a startup team's group chat. Given the "
    "recent conversation, the team's strategic items, and reference material, "
    "decide whether you have ONE contribution that genuinely adds value. Kinds: "
    "connection (link what's being said to an existing strategic item), "
    "knowledge (bring a relevant point from the reference material), "
    "question (a socratic question that deepens a shallow discussion), "
    "synthesis (summarize positions when a topic drags on). "
    "If nothing truly adds value, return should_contribute=false. Never repeat "
    "what was just said. Return JSON {\"should_contribute\": bool, "
    "\"relevance\": 0..1, \"kind\": connection|knowledge|question|synthesis or null, "
    "\"text\": the contribution, 1-3 sentences, in the conversation's language}."
)

RESPOND_SYSTEM = (
    "You are a helpful member of a startup team's group chat and someone "
    "addressed you directly. Answer conversationally and concisely using the "
    "recent conversation, the team's strategic items, and the reference "
    "material. Answer in the conversation's language. "
    "Return JSON {\"text\": your reply}."
)


def _context(window, items, materials):
    convo = "\n".join(f"{m['author']}: {m['text']}" for m in window)
    items_txt = "\n".join(f"[{i['type']}] {i['content']}" for i in items)
    return (
        f"CONVERSATION:\n{convo}\n\n"
        f"STRATEGIC ITEMS:\n{items_txt}\n\n"
        f"REFERENCE MATERIAL:\n{materials}"
    )


class Participant:
    def __init__(self, executor, consider_agent=None, respond_agent=None):
        self.executor = executor
        self.consider_agent = consider_agent
        self.respond_agent = respond_agent

    def consider(self, window, items, materials, style=""):
        user = _context(window, items, materials)
        if style:
            user += f"\n\nWrite in this voice: {style}"
        result = self.executor.run_validated(self.consider_agent, user, Contribution)
        if result is not None:
            result.text = _unwrap_text(result.text)
        return result

    def respond(self, window, items, materials, mention_text, style=""):
        user = _context(window, items, materials) + f"\n\nADDRESSED TO YOU:\n{mention_text}"
        if style:
            user += f"\n\nWrite in this voice: {style}"
        result = self.executor.run_validated(self.respond_agent, user, StyledText)
        return _unwrap_text(result.text) if result is not None else None
