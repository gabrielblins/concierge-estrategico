from concierge.stylist import Stylist, PRESETS


def test_presets_have_expected_names():
    assert set(PRESETS) == {"mentor", "coach", "zen", "formal"}
    assert all(isinstance(v, str) and v for v in PRESETS.values())


def test_restyle_empty_personality_skips_llm(fake_llm):
    llm = fake_llm(responses=[])
    s = Stylist(llm)
    assert s.restyle("Canvas atualizado.", "") == "Canvas atualizado."
    assert s.restyle("Canvas atualizado.", "   ") == "Canvas atualizado."
    assert llm.calls == []


def test_restyle_rewrites_in_voice(fake_llm):
    llm = fake_llm(responses=[{"text": "Aí sim! Canvas atualizado, time! 🚀"}])
    s = Stylist(llm)
    out = s.restyle("Canvas atualizado.", PRESETS["coach"])
    assert out == "Aí sim! Canvas atualizado, time! 🚀"
    # prompt carries both the personality and the original text
    assert PRESETS["coach"] in llm.calls[0][0] or PRESETS["coach"] in llm.calls[0][1]
    assert "Canvas atualizado." in llm.calls[0][1]


def test_restyle_falls_back_on_llm_failure(fake_llm):
    llm = fake_llm(responses=[{"bad": 1}, {"bad": 1}])
    s = Stylist(llm)
    assert s.restyle("Canvas atualizado.", "voz qualquer") == "Canvas atualizado."
