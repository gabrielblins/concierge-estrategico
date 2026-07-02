import sqlite3
import time

import pytest
from fastapi.testclient import TestClient

from concierge.config import Settings
from concierge.storage import Storage
from concierge.models import ItemType, ItemStatus
from concierge.webapp.server import create_app
from tests.test_webapp_auth import sign_init_data

TOKEN = "123456:TEST-TOKEN"


@pytest.fixture
def client_and_storage():
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    st = Storage(conn)
    st.init_schema()
    settings = Settings(telegram_token=TOKEN, openai_api_key="k")
    app = create_app(settings, storage=st)
    return TestClient(app), st


def _init(chat_id, auth_date=None):
    if auth_date is None:
        auth_date = str(int(time.time()))
    return sign_init_data({"auth_date": auth_date, "start_param": str(chat_id)}, TOKEN)


def test_unauthorized_without_valid_init_data(client_and_storage):
    client, _ = client_and_storage
    r = client.post("/api/canvas", json={"init_data": "auth_date=1&hash=deadbeef"})
    assert r.status_code == 401


def test_400_when_start_param_missing(client_and_storage):
    client, _ = client_and_storage
    init = sign_init_data({"auth_date": str(int(time.time()))}, TOKEN)
    r = client.post("/api/canvas", json={"init_data": init})
    assert r.status_code == 400


def test_404_when_project_absent(client_and_storage):
    client, _ = client_and_storage
    r = client.post("/api/canvas", json={"init_data": _init(-777)})
    assert r.status_code == 404


def test_canvas_payload(client_and_storage):
    client, st = client_and_storage
    pid = st.get_or_create_project(-500, "Acme")
    st.upsert_block(pid, "customer_segments", "SMBs brasileiras", [1])
    i1 = st.add_item(pid, ItemType.HYPOTHESIS, "SMBs pagam", 0.9, None,
                     status=ItemStatus.VALIDATED)
    st.add_item(pid, ItemType.DECISION, "descartada", 0.5, None,
                status=ItemStatus.DISCARDED)
    r = client.post("/api/canvas", json={"init_data": _init(-500)})
    assert r.status_code == 200
    data = r.json()
    assert data["project"]["name"] == "Acme"
    assert data["project"]["updated_at"] > 0
    assert data["blocks"] == [
        {"block_name": "customer_segments", "content": "SMBs brasileiras", "item_ids": [1]}
    ]
    assert [i["id"] for i in data["items"]] == [i1]
    assert data["items"][0]["status"] == "validated"


def test_empty_canvas_returns_200(client_and_storage):
    client, st = client_and_storage
    st.get_or_create_project(-501, "Vazio")
    r = client.post("/api/canvas", json={"init_data": _init(-501)})
    assert r.status_code == 200
    body = r.json()
    assert body["blocks"] == [] and body["project"]["updated_at"] is None


def test_index_served_with_full_grid(client_and_storage):
    client, _ = client_and_storage
    r = client.get("/")
    assert r.status_code == 200
    for block in ["value_proposition", "customer_segments", "channels",
                  "customer_relationships", "revenue_streams", "key_resources",
                  "key_activities", "key_partnerships", "cost_structure"]:
        assert block in r.text
    assert "telegram-web-app.js" in r.text
    assert "themeParams" in r.text
