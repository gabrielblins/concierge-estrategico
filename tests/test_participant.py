from concierge.participant import Participant
from concierge.models import Contribution, ContributionKind, StyledText

WINDOW = [{"id": 1, "author": "ana", "text": "e se focarmos em healthtechs?"},
          {"id": 2, "author": "bob", "text": "pode ser, mas não sei"}]
ITEMS = [{"type": "hypothesis", "content": "SMBs pagam pela economia de tempo"}]


def test_consider_returns_contribution_with_context_in_prompt(fake_executor):
    ex = fake_executor(results=[Contribution(
        should_contribute=True, relevance=0.9, kind=ContributionKind.CONNECTION,
        text="Isso conversa com a hipótese validada de SMBs — healthtechs são um recorte dela?",
    )])
    p = Participant(ex)
    c = p.consider(WINDOW, ITEMS, "trecho do manual", style="")
    assert c.should_contribute and c.kind == ContributionKind.CONNECTION
    user = ex.calls[0][1]
    assert "healthtechs" in user and "SMBs pagam" in user and "trecho do manual" in user


def test_consider_style_injected_and_failure_silent(fake_executor):
    ex = fake_executor(results=[Contribution(
        should_contribute=False, relevance=0.1, kind=None, text="",
    )])
    p = Participant(ex)
    p.consider(WINDOW, [], "", style="voz de coach")
    assert "voz de coach" in ex.calls[0][1]
    broken = Participant(fake_executor(results=[None]))
    assert broken.consider(WINDOW, [], "") is None


def test_respond_returns_text_and_includes_mention(fake_executor):
    ex = fake_executor(results=[StyledText(text="Na minha visão, vale testar com 5 clientes.")])
    p = Participant(ex)
    out = p.respond(WINDOW, ITEMS, "", "o que você acha, bot?", style="")
    assert out == "Na minha visão, vale testar com 5 clientes."
    assert "ADDRESSED TO YOU" in ex.calls[0][1]
    assert "o que você acha, bot?" in ex.calls[0][1]


def test_respond_failure_silent(fake_executor):
    p = Participant(fake_executor(results=[None]))
    assert p.respond(WINDOW, [], "", "oi bot") is None


def test_respond_unwraps_double_encoded_json(fake_executor):
    ex = fake_executor(results=[StyledText(text='{"text":"Na minha visão, testem com 5 clientes."}')])
    p = Participant(ex)
    out = p.respond(WINDOW, [], "", "oi bot")
    assert out == "Na minha visão, testem com 5 clientes."


def test_consider_unwraps_double_encoded_text(fake_executor):
    ex = fake_executor(results=[Contribution(
        should_contribute=True, relevance=0.9, kind=ContributionKind.QUESTION,
        text='{"text":"Qual evidência sustenta isso?"}',
    )])
    p = Participant(ex)
    c = p.consider(WINDOW, [], "")
    assert c.text == "Qual evidência sustenta isso?"


def test_unwrap_leaves_normal_and_braced_prose_alone():
    from concierge.participant import _unwrap_text
    assert _unwrap_text("texto normal") == "texto normal"
    assert _unwrap_text('{"other": "shape"}') == '{"other": "shape"}'
    assert _unwrap_text("{isso não é json") == "{isso não é json"
    assert _unwrap_text("") == ""
