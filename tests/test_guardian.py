from concierge.guardian import Guardian


def test_looks_strategic_prefilter():
    g = Guardian(llm=None)
    assert g.looks_strategic("Vamos priorizar o segmento enterprise") is True
    assert g.looks_strategic("kkk ok") is False
    assert g.looks_strategic("acho que devemos decidir isso") is True


def test_check_returns_verdict(fake_llm):
    llm = fake_llm(responses=[{
        "contradicts": True,
        "item_content": "We validated focusing on SMBs",
        "reason": "This proposes enterprise, contradicting the validated SMB focus",
        "confidence": 0.88,
    }])
    g = Guardian(llm)
    verdict = g.check(
        text="let's target big enterprises now",
        known_items=[{"type": "hypothesis", "content": "We validated focusing on SMBs"}],
    )
    assert verdict.contradicts is True
    assert verdict.confidence == 0.88


def test_check_returns_none_on_invalid(fake_llm):
    llm = fake_llm(responses=[{"bad": 1}, {"bad": 1}])
    g = Guardian(llm)
    assert g.check("x", []) is None
