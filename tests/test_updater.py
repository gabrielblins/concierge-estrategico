from concierge.updater import CanvasUpdater
from concierge.models import CanvasUpdateResult, CanvasBlockUpdate


def test_update_returns_valid_blocks_only(fake_executor):
    ex = fake_executor(results=[CanvasUpdateResult(blocks=[
        CanvasBlockUpdate(block_name="value_proposition", content="Save time"),
        CanvasBlockUpdate(block_name="not_a_real_block", content="junk"),
    ])])
    up = CanvasUpdater(ex)
    blocks = up.update(
        active_items=[{"type": "decision", "content": "Target SMBs"}],
        current_blocks=[],
    )
    names = [b.block_name for b in blocks]
    assert "value_proposition" in names
    assert "not_a_real_block" not in names


def test_update_returns_empty_on_none(fake_executor):
    ex = fake_executor(results=[None])
    up = CanvasUpdater(ex)
    assert up.update([], []) == []


def test_update_appends_reference_material(fake_executor):
    ex = fake_executor(results=[CanvasUpdateResult(blocks=[])])
    CanvasUpdater(ex).update([], [], context="manual do canvas diz Y")
    assert "REFERENCE MATERIAL:\nmanual do canvas diz Y" in ex.calls[0][1]
