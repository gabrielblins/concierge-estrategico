from concierge.stylist import Stylist, PRESETS
from concierge.models import StyledText


def test_presets_have_expected_names():
    assert set(PRESETS) == {"mentor", "coach", "zen", "formal"}
    assert all(isinstance(v, str) and v for v in PRESETS.values())


def test_restyle_empty_personality_skips_executor(fake_executor):
    ex = fake_executor(results=[])
    s = Stylist(ex)
    assert s.restyle("Canvas atualizado.", "") == "Canvas atualizado."
    assert s.restyle("Canvas atualizado.", "   ") == "Canvas atualizado."
    assert ex.calls == []


def test_restyle_rewrites_in_voice(fake_executor):
    ex = fake_executor(results=[StyledText(text="Aí sim! Canvas atualizado, time! 🚀")])
    s = Stylist(ex)
    out = s.restyle("Canvas atualizado.", PRESETS["coach"])
    assert out == "Aí sim! Canvas atualizado, time! 🚀"
    # prompt carries both the personality and the original text
    assert PRESETS["coach"] in ex.calls[0][1]
    assert "Canvas atualizado." in ex.calls[0][1]


def test_restyle_falls_back_on_executor_failure(fake_executor):
    ex = fake_executor(results=[None])
    s = Stylist(ex)
    assert s.restyle("Canvas atualizado.", "voz qualquer") == "Canvas atualizado."
