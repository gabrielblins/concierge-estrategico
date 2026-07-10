from concierge.agents.funnel import MessageFunnelAgent
from concierge.models import CoherenceVerdict, Contribution


class _G:  # guardian facade stub
    def __init__(self, verdict):
        self.verdict = verdict
        self.calls = []

    def check(self, text, known_items, method_context="", style=""):
        self.calls.append(text)
        return self.verdict


class _P:  # participant facade stub
    def __init__(self, contribution):
        self.contribution = contribution
        self.calls = []

    def consider(self, window, items, materials, style=""):
        self.calls.append(window)
        return self.contribution


def _funnel(verdict=None, contribution=None, ct=0.75, pt=0.75):
    return MessageFunnelAgent(
        name="funnel", guardian_facade=_G(verdict), participant_facade=_P(contribution),
        confidence_threshold=ct, participation_threshold=pt,
    )


def _inputs(**kw):
    base = dict(text="vamos priorizar enterprise", known_items=[], window=[],
                items=[], materials_guardian="", materials_participant="",
                style="")
    base.update(kw)
    return base


def test_silent_gate_short_circuits():
    f = _funnel(verdict=CoherenceVerdict(contradicts=True, reason="x",
                                         confidence=0.9))
    out = f.decide(gates={"silent": True, "participation_ok": True}, **_inputs())
    assert out == {"decision": "none"}
    assert f.guardian_facade.calls == []


def test_guardian_alert_wins_and_participant_never_runs():
    f = _funnel(
        verdict=CoherenceVerdict(contradicts=True, item_content="X",
                                 reason="conflita", confidence=0.9),
        contribution=Contribution(should_contribute=True, relevance=0.9,
                                  kind="question", text="?"),
    )
    out = f.decide(gates={"silent": False, "participation_ok": True}, **_inputs())
    assert out["decision"] == "alert" and out["confidence"] == 0.9
    assert f.participant_facade.calls == []


def test_low_confidence_falls_through_to_participant():
    f = _funnel(
        verdict=CoherenceVerdict(contradicts=True, reason="meh", confidence=0.5),
        contribution=Contribution(should_contribute=True, relevance=0.9,
                                  kind="connection", text="liga com X"),
    )
    out = f.decide(gates={"silent": False, "participation_ok": True}, **_inputs())
    assert out == {"decision": "contribution", "text": "liga com X"}


def test_participation_gate_blocks_consider():
    f = _funnel(verdict=None, contribution=Contribution(
        should_contribute=True, relevance=0.9, kind="question", text="?"))
    out = f.decide(gates={"silent": False, "participation_ok": False}, **_inputs())
    assert out == {"decision": "none"}
    assert f.participant_facade.calls == []


def test_never_raises_on_none_verdict_and_contribution():
    f = _funnel(verdict=None, contribution=None)
    out = f.decide(gates={"silent": False, "participation_ok": True}, **_inputs())
    assert out == {"decision": "none"}
