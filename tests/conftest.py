import sqlite3
import pytest
from concierge.storage import Storage
from concierge.llm.client import FakeLLMClient


@pytest.fixture
def storage():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    s = Storage(conn)
    s.init_schema()
    return s


@pytest.fixture
def fake_llm():
    def _make(responses=None, error=None):
        return FakeLLMClient(responses=responses, error=error)
    return _make


class FakeExecutor:
    def __init__(self, results=None):
        self._results = list(results or [])
        self.calls = []

    def run_validated(self, agent, user_text, schema):
        self.calls.append((getattr(agent, "name", agent), user_text, schema))
        return self._results.pop(0) if self._results else None

    def run_text(self, agent, user_text):
        self.calls.append((getattr(agent, "name", agent), user_text, None))
        return self._results.pop(0) if self._results else None


@pytest.fixture
def fake_executor():
    def _make(results=None):
        return FakeExecutor(results=results)
    return _make
