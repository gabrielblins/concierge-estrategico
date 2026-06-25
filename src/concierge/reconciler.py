from concierge.llm.client import call_validated
from concierge.models import ReconciliationResult, ItemStatus

SYSTEM = (
    "You reconcile a startup's strategic items. Given newly-added items and the "
    "existing active items, decide which items the team has now VALIDATED or "
    "DISCARDED, and which existing item (if any) each one supersedes. "
    "Return JSON {\"transitions\": [{\"item_id\": int, "
    "\"new_status\": one of validated|discarded, "
    "\"supersedes_id\": int or null}]}. Only include items whose status actually "
    "changed; leave the rest active by omitting them."
)

_ALLOWED = {ItemStatus.VALIDATED, ItemStatus.DISCARDED}


class Reconciler:
    def __init__(self, llm):
        self.llm = llm

    def reconcile(self, new_items, active_items):
        known_ids = {i["id"] for i in new_items} | {i["id"] for i in active_items}
        new_txt = "\n".join(f"#{i['id']} [{i['type']}] {i['content']}" for i in new_items)
        active_txt = "\n".join(f"#{i['id']} [{i['type']}] {i['content']}" for i in active_items)
        user = f"NEW ITEMS:\n{new_txt}\n\nEXISTING ACTIVE ITEMS:\n{active_txt}"
        result = call_validated(self.llm, SYSTEM, user, ReconciliationResult)
        if result is None:
            return []
        return [
            t for t in result.transitions
            if t.new_status in _ALLOWED and t.item_id in known_ids
        ]
