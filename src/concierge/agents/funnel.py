import asyncio
import json

from google.adk.agents.base_agent import BaseAgent
from google.genai import types

try:  # Event import location per spike
    from google.adk.events import Event
except ImportError:  # pragma: no cover
    from google.adk.events.event import Event
from google.adk.events.event_actions import EventActions


class MessageFunnelAgent(BaseAgent):
    """Deterministic ADK orchestrator for the non-mention message path.

    Gates and priority are code; the LLM work happens in the guardian and
    participant facades (each backed by its own ADK LlmAgent + executor).
    """

    model_config = {"arbitrary_types_allowed": True}

    guardian_facade: object
    participant_facade: object
    confidence_threshold: float = 0.75
    participation_threshold: float = 0.75

    def decide(self, gates, text, known_items, window, items,
               materials_guardian, materials_participant, style):
        if gates.get("silent"):
            return {"decision": "none"}
        verdict = self.guardian_facade.check(
            text, known_items, materials_guardian, style=style
        )
        if (verdict is not None and verdict.contradicts
                and verdict.confidence >= self.confidence_threshold):
            return {
                "decision": "alert",
                "reason": verdict.reason,
                "confidence": verdict.confidence,
                "item_content": verdict.item_content,
            }
        if not gates.get("participation_ok"):
            return {"decision": "none"}
        c = self.participant_facade.consider(
            window, items, materials_participant, style=style
        )
        if (c is not None and c.should_contribute
                and c.relevance >= self.participation_threshold
                and c.text.strip()):
            return {"decision": "contribution", "text": c.text}
        return {"decision": "none"}

    async def _run_async_impl(self, ctx):
        state = ctx.session.state
        result = await asyncio.to_thread(
            self.decide,
            gates=state.get("gates", {}),
            text=state.get("text", ""),
            known_items=state.get("known_items", []),
            window=state.get("window", []),
            items=state.get("items", []),
            materials_guardian=state.get("materials_guardian", ""),
            materials_participant=state.get("materials_participant", ""),
            style=state.get("style", ""),
        )
        yield Event(
            author=self.name,
            actions=EventActions(state_delta={"result": result}),
            content=types.Content(
                role="model", parts=[types.Part(text=json.dumps(result))]
            ),
        )
