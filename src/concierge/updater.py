from concierge.models import CanvasUpdateResult
from concierge.canvas import BMC_BLOCKS

SYSTEM = (
    "You maintain a Business Model Canvas for a startup. "
    "Given the current strategic items and current canvas blocks, "
    "return JSON {\"blocks\": [{\"block_name\": one of the nine BMC block names, "
    "\"content\": synthesized text}]}. Only return blocks that changed. "
    f"Valid block names: {', '.join(BMC_BLOCKS)}."
)


class CanvasUpdater:
    def __init__(self, executor, agent=None):
        self.executor = executor
        self.agent = agent

    def update(self, active_items, current_blocks, context=""):
        items_txt = "\n".join(f"[{i['type']}] {i['content']}" for i in active_items)
        blocks_txt = "\n".join(f"{b['block_name']}: {b['content']}" for b in current_blocks)
        user = f"STRATEGIC ITEMS:\n{items_txt}\n\nCURRENT CANVAS:\n{blocks_txt}"
        if context:
            user += f"\n\nREFERENCE MATERIAL:\n{context}"
        result = self.executor.run_validated(self.agent, user, CanvasUpdateResult)
        if result is None:
            return []
        return [b for b in result.blocks if b.block_name in BMC_BLOCKS]
