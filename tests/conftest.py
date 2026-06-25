import sqlite3
import pytest
from concierge.storage import Storage


@pytest.fixture
def storage():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    s = Storage(conn)
    s.init_schema()
    return s
