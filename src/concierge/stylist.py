from concierge.llm.client import call_validated
from concierge.models import StyledText

PRESETS = {
    "mentor": (
        "Fale como um mentor direto e experiente: sem rodeios, aponte o risco "
        "e sugira o próximo passo concreto."
    ),
    "coach": (
        "Fale como um coach motivacional: energético, celebre o progresso "
        "antes de apontar desvios."
    ),
    "zen": (
        "Fale como um conselheiro zen: calmo, socrático — prefira perguntas "
        "que levem a equipe a enxergar o problema."
    ),
    "formal": (
        "Fale como um consultor formal: analítico, impessoal, tom de "
        "relatório executivo."
    ),
}

SYSTEM = (
    "You rewrite short bot messages in a given voice. Keep ALL factual "
    "content intact — numbers, names, block names, commands like /status — "
    "change only the tone. Answer in the same language as the message. "
    "Return JSON {\"text\": rewritten message}."
)


class Stylist:
    def __init__(self, llm):
        self.llm = llm

    def restyle(self, text: str, personality: str) -> str:
        if not personality or not personality.strip():
            return text
        user = f"VOICE:\n{personality}\n\nMESSAGE:\n{text}"
        result = call_validated(self.llm, SYSTEM, user, StyledText)
        if result is None:
            return text
        return result.text
