from google.adk.agents import LlmAgent

from concierge.extractor import SYSTEM as EXTRACTOR_SYSTEM
from concierge.guardian import SYSTEM as GUARDIAN_SYSTEM
from concierge.materials import CLASSIFY_SYSTEM
from concierge.participant import CONSIDER_SYSTEM, RESPOND_SYSTEM
from concierge.reconciler import SYSTEM as RECONCILER_SYSTEM
from concierge.stylist import SYSTEM as STYLIST_SYSTEM
from concierge.updater import SYSTEM as UPDATER_SYSTEM

AGENT_NAMES = [
    "extractor", "reconciler", "canvas_updater", "guardian",
    "participant_consider", "participant_respond", "stylist",
    "material_classifier",
]

INSTRUCTIONS = {
    "extractor": EXTRACTOR_SYSTEM,
    "reconciler": RECONCILER_SYSTEM,
    "canvas_updater": UPDATER_SYSTEM,
    "guardian": GUARDIAN_SYSTEM,
    "participant_consider": CONSIDER_SYSTEM,
    "participant_respond": RESPOND_SYSTEM,
    "stylist": STYLIST_SYSTEM,
    "material_classifier": CLASSIFY_SYSTEM,
}


def build_agents(model):
    return {
        name: LlmAgent(name=name, model=model, instruction=INSTRUCTIONS[name])
        for name in AGENT_NAMES
    }
