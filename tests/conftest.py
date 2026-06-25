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
