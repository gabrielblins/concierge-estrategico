from concierge.participant import Participant
from concierge.models import ContributionKind

WINDOW = [{"id": 1, "author": "ana", "text": "e se focarmos em healthtechs?"},
          {"id": 2, "author": "bob", "text": "pode ser, mas não sei"}]
ITEMS = [{"type": "hypothesis", "content": "SMBs pagam pela economia de tempo"}]


def test_consider_returns_contribution_with_context_in_prompt(fake_llm):
    llm = fake_llm(responses=[{
        "should_contribute": True, "relevance": 0.9, "kind": "connection",
        "text": "Isso conversa com a hipótese validada de SMBs — healthtechs são um recorte dela?",
    }])
    p = Participant(llm)
    c = p.consider(WINDOW, ITEMS, "trecho do manual", style="")
    assert c.should_contribute and c.kind == ContributionKind.CONNECTION
    user = llm.calls[0][1]
    assert "healthtechs" in user and "SMBs pagam" in user and "trecho do manual" in user


def test_consider_style_injected_and_failure_silent(fake_llm):
    llm = fake_llm(responses=[{
        "should_contribute": False, "relevance": 0.1, "kind": None, "text": "",
    }])
    p = Participant(llm)
    p.consider(WINDOW, [], "", style="voz de coach")
    assert "voz de coach" in llm.calls[0][0]
    broken = Participant(fake_llm(responses=[{"bad": 1}, {"bad": 1}]))
    assert broken.consider(WINDOW, [], "") is None


def test_respond_returns_text_and_includes_mention(fake_llm):
    llm = fake_llm(responses=[{"text": "Na minha visão, vale testar com 5 clientes."}])
    p = Participant(llm)
    out = p.respond(WINDOW, ITEMS, "", "o que você acha, bot?", style="")
    assert out == "Na minha visão, vale testar com 5 clientes."
    assert "ADDRESSED TO YOU" in llm.calls[0][1]
    assert "o que você acha, bot?" in llm.calls[0][1]


def test_respond_failure_silent(fake_llm):
    p = Participant(fake_llm(responses=[{"nope": 1}, {"nope": 1}]))
    assert p.respond(WINDOW, [], "", "oi bot") is None


def test_respond_unwraps_double_encoded_json(fake_llm):
    llm = fake_llm(responses=[{"text": '{"text":"Na minha visão, testem com 5 clientes."}'}])
    p = Participant(llm)
    out = p.respond(WINDOW, [], "", "oi bot")
    assert out == "Na minha visão, testem com 5 clientes."


def test_consider_unwraps_double_encoded_text(fake_llm):
    llm = fake_llm(responses=[{
        "should_contribute": True, "relevance": 0.9, "kind": "question",
        "text": '{"text":"Qual evidência sustenta isso?"}',
    }])
    p = Participant(llm)
    c = p.consider(WINDOW, [], "")
    assert c.text == "Qual evidência sustenta isso?"


def test_unwrap_leaves_normal_and_braced_prose_alone(fake_llm):
    from concierge.participant import _unwrap_text
    assert _unwrap_text("texto normal") == "texto normal"
    assert _unwrap_text('{"other": "shape"}') == '{"other": "shape"}'
    assert _unwrap_text("{isso não é json") == "{isso não é json"
    assert _unwrap_text("") == ""
