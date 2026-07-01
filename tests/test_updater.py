from concierge.updater import CanvasUpdater


def test_update_returns_valid_blocks_only(fake_llm):
    llm = fake_llm(responses=[{
        "blocks": [
            {"block_name": "value_proposition", "content": "Save time"},
            {"block_name": "not_a_real_block", "content": "junk"},
        ]
    }])
    up = CanvasUpdater(llm)
    blocks = up.update(
        active_items=[{"type": "decision", "content": "Target SMBs"}],
        current_blocks=[],
    )
    names = [b.block_name for b in blocks]
    assert "value_proposition" in names
    assert "not_a_real_block" not in names


def test_update_returns_empty_on_invalid(fake_llm):
    llm = fake_llm(responses=[{"blocks": "bad"}, {"blocks": "bad"}])
    up = CanvasUpdater(llm)
    assert up.update([], []) == []


def test_update_appends_reference_material(fake_llm):
    llm = fake_llm(responses=[{"blocks": []}])
    CanvasUpdater(llm).update([], [], context="manual do canvas diz Y")
    assert "REFERENCE MATERIAL:\nmanual do canvas diz Y" in llm.calls[0][1]
