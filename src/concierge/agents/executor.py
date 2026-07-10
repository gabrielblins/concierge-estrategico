import asyncio
import json
import threading
import uuid

from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types
from pydantic import ValidationError


class AgentExecutor:
    """Runs ADK agents from synchronous code.

    Owns a dedicated event loop in a daemon thread so callers inside an
    already-running loop (the telegram bot) can block on agent results.
    """

    def __init__(self):
        self._loop = None
        self._lock = threading.Lock()

    def _ensure_loop(self):
        with self._lock:
            if self._loop is None:
                self._loop = asyncio.new_event_loop()
                thread = threading.Thread(
                    target=self._loop.run_forever, daemon=True,
                    name="adk-executor",
                )
                thread.start()
        return self._loop

    def _submit(self, coro):
        loop = self._ensure_loop()
        return asyncio.run_coroutine_threadsafe(coro, loop).result()

    async def _run(self, agent, user_text):
        session_service = InMemorySessionService()
        runner = Runner(
            app_name="concierge", agent=agent, session_service=session_service
        )
        session = await session_service.create_session(
            app_name="concierge", user_id="bot",
            session_id=uuid.uuid4().hex,
        )
        final = ""
        async for event in runner.run_async(
            user_id="bot", session_id=session.id,
            new_message=types.Content(
                role="user", parts=[types.Part(text=user_text)]
            ),
        ):
            if event.content and event.content.parts:
                for part in event.content.parts:
                    if part.text:
                        final = part.text
        return final

    def run_text(self, agent, user_text):
        try:
            return self._submit(self._run(agent, user_text))
        except Exception:
            return None

    def run_validated(self, agent, user_text, schema):
        for _ in range(2):
            text = self.run_text(agent, user_text)
            if text is None:
                continue
            try:
                return schema.model_validate(json.loads(text))
            except (ValueError, ValidationError):
                continue
        return None
