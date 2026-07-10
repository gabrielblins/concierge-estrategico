from concierge.agents.definitions import AGENT_NAMES, INSTRUCTIONS, build_agents
from tests.test_agents_spike import FakeAdkModel


def test_all_eight_agents_defined():
    assert AGENT_NAMES == [
        "extractor", "reconciler", "canvas_updater", "guardian",
        "participant_consider", "participant_respond", "stylist",
        "material_classifier",
    ]
    assert set(INSTRUCTIONS) == set(AGENT_NAMES)


def test_instructions_carry_the_original_contracts():
    assert "decision|hypothesis|premise|risk|task|learning" in INSTRUCTIONS["extractor"]
    assert "contradicts" in INSTRUCTIONS["guardian"]
    assert "should_contribute" in INSTRUCTIONS["participant_consider"]
    assert "validated|discarded" in INSTRUCTIONS["reconciler"]
    assert "block_name" in INSTRUCTIONS["canvas_updater"]
    assert "canvas_guide|validation_guide" in INSTRUCTIONS["material_classifier"]


def test_build_agents_wires_model_and_instruction():
    model = FakeAdkModel(responses=[])
    agents = build_agents(model)
    assert set(agents) == set(AGENT_NAMES)
    assert agents["guardian"].instruction == INSTRUCTIONS["guardian"]
    assert agents["guardian"].model is model
