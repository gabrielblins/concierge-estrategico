from concierge.guardian import Guardian
from concierge.models import CoherenceVerdict


def test_looks_strategic_prefilter():
    g = Guardian(None)
    assert g.looks_strategic("Vamos priorizar o segmento enterprise") is True
    assert g.looks_strategic("kkk ok") is False
    assert g.looks_strategic("acho que devemos decidir isso") is True


def test_check_returns_verdict(fake_executor):
    ex = fake_executor(results=[CoherenceVerdict(
        contradicts=True,
        item_content="We validated focusing on SMBs",
        reason="This proposes enterprise, contradicting the validated SMB focus",
        confidence=0.88,
    )])
    g = Guardian(ex)
    verdict = g.check(
        text="let's target big enterprises now",
        known_items=[{"type": "hypothesis", "content": "We validated focusing on SMBs"}],
    )
    assert verdict.contradicts is True
    assert verdict.confidence == 0.88


def test_check_returns_none_on_invalid(fake_executor):
    ex = fake_executor(results=[None])
    g = Guardian(ex)
    assert g.check("x", []) is None


def test_check_injects_style_into_user_prompt(fake_executor):
    ex = fake_executor(results=[CoherenceVerdict(
        contradicts=False, item_content=None, reason="ok", confidence=0.1,
    )])
    g = Guardian(ex)
    g.check("vamos mudar o foco", [], style="fale como um pirata")
    user_sent = ex.calls[0][1]
    assert "fale como um pirata" in user_sent
    assert "Write the 'reason' field in this voice" in user_sent


def test_check_without_style_keeps_prompt_clean(fake_executor):
    ex = fake_executor(results=[CoherenceVerdict(
        contradicts=False, item_content=None, reason="ok", confidence=0.1,
    )])
    g = Guardian(ex)
    g.check("vamos mudar o foco", [])
    assert "voice" not in ex.calls[0][1].lower()
