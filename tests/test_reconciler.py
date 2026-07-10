from concierge.reconciler import Reconciler
from concierge.models import ItemStatus, ReconciliationResult, ItemTransition


def test_reconcile_returns_valid_transitions(fake_executor):
    ex = fake_executor(results=[ReconciliationResult(transitions=[
        ItemTransition(item_id=1, new_status=ItemStatus.VALIDATED, supersedes_id=None),
        ItemTransition(item_id=2, new_status=ItemStatus.DISCARDED, supersedes_id=1),
    ])])
    r = Reconciler(ex)
    out = r.reconcile(
        new_items=[{"id": 1, "type": "hypothesis", "content": "SMBs will pay"}],
        active_items=[{"id": 2, "type": "decision", "content": "target enterprise"}],
    )
    assert len(out) == 2
    assert out[0].new_status == ItemStatus.VALIDATED


def test_reconcile_drops_unknown_ids_and_bad_status(fake_executor):
    ex = fake_executor(results=[ReconciliationResult.model_validate({
        "transitions": [
            {"item_id": 999, "new_status": "validated", "supersedes_id": None},
            {"item_id": 1, "new_status": "active", "supersedes_id": None},
        ]
    })])
    r = Reconciler(ex)
    out = r.reconcile(new_items=[{"id": 1, "type": "decision", "content": "x"}], active_items=[])
    # item 999 unknown -> dropped; status 'active' is not validated/discarded -> dropped
    assert out == []


def test_reconcile_returns_empty_on_none(fake_executor):
    ex = fake_executor(results=[None])
    r = Reconciler(ex)
    assert r.reconcile([], []) == []


def test_reconcile_appends_reference_material(fake_executor):
    ex = fake_executor(results=[ReconciliationResult(transitions=[])])
    Reconciler(ex).reconcile([{"id": 1, "type": "decision", "content": "x"}], [],
                             context="valide com 5 clientes")
    assert "REFERENCE MATERIAL:\nvalide com 5 clientes" in ex.calls[0][1]
