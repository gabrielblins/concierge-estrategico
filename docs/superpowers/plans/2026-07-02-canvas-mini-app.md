# Canvas Mini App Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `/canvas` in a group posts a direct-link button that opens a Telegram Mini App showing the live Business Model Canvas (9-block grid, tap for strategic items), served by a separate FastAPI process reading the same SQLite database.

**Architecture:** New package `webapp/` — `auth.py` validates Telegram `initData` (HMAC, per official algorithm) and the signed `start_param` carries the chat id; `server.py` is a FastAPI factory (`create_app`) with `GET /` (static page) and `POST /api/canvas` (validated JSON payload); `static/index.html` is a framework-free single page using `telegram-web-app.js` and Telegram theme vars. The bot gains a `/canvas` command that links to `https://t.me/<bot_username>/<WEBAPP_APP_NAME>?startapp=<chat_id>` (web_app buttons don't work in groups — see spec addendum). Storage gains WAL mode for cross-process reads.

**Tech Stack:** Python 3.14, fastapi 0.139.0, uvicorn 0.49.0, httpx 0.28.1 (TestClient), stdlib hmac/hashlib, HTML/CSS/JS puro.

## Global Constraints

- Auth: every data response requires valid `init_data` (HMAC with secret = HMAC_SHA256(key="WebAppData", msg=bot_token); constant-time compare; `auth_date` ≤ 1h). Invalid → 401. `chat_id` comes ONLY from the validated payload's `start_param` (spec addendum) — the request body is `{init_data}` alone.
- The webapp process only READS the DB; no write route exists. `PRAGMA journal_mode=WAL` in `init_schema`.
- Payload shape (spec §3.2): `{project: {name, updated_at}, blocks: [{block_name, content, item_ids}], items: [{id, type, content, status}]}`; items = ACTIVE+VALIDATED.
- Errors: 401 unauthorized; 400 missing/invalid start_param; 404 chat without project; DB locked → one retry then 503. Empty canvas → 200 with `blocks: []`.
- Env names exactly: `WEBAPP_APP_NAME` (BotFather short name, default ""), `WEBAPP_PORT` (default 8080).
- `/canvas` requires the `/start` gate; missing `WEBAPP_APP_NAME` → friendly config message.
- Frontend: 9 exact BMC block names present in the HTML; loads `https://telegram.org/js/telegram-web-app.js`; applies `themeParams`; states loading/empty/error.
- All business logic testable without network (TestClient, in-memory storage, initData signed in tests with a fake token).
- Shared venv `. .venv/bin/activate` (Python 3.14.3). Suite currently at 117 passed.

---

## File Structure

```
src/concierge/webapp/
  __init__.py       # empty
  __main__.py       # python -m concierge.webapp → server.main()
  auth.py           # validate_init_data, parse_init_data
  server.py         # create_app(settings, storage=None), main()
  static/index.html # single-page mini app
src/concierge/
  config.py         # +webapp_app_name, +webapp_port
  storage.py        # +WAL pragma, +get_project_name, +canvas_updated_at
  bot.py            # +handle_canvas + /canvas closure/registration
tests/
  test_webapp_auth.py
  test_webapp_server.py
  + additions to test_config/test_storage/test_bot
requirements.txt    # +fastapi, +uvicorn, +httpx
.env.example, README.md, SETUP.md
```

---

### Task 1: Config and storage support

**Files:**
- Modify: `src/concierge/config.py`, `src/concierge/storage.py`, `.env.example`
- Modify: `tests/test_config.py`, `tests/test_storage.py`

**Interfaces:**
- Produces: `Settings.webapp_app_name: str = ""` (env `WEBAPP_APP_NAME`), `Settings.webapp_port: int = 8080` (env `WEBAPP_PORT`). Storage: `init_schema` executes `PRAGMA journal_mode=WAL` (before the executescript); `get_project_name(project_id) -> str` (`""` if missing); `canvas_updated_at(project_id) -> float | None` (MAX(updated_at) of the project's canvas_blocks; None when no blocks).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_config.py`:

```python
def test_settings_webapp_fields(monkeypatch):
    monkeypatch.setenv("TELEGRAM_TOKEN", "tok")
    monkeypatch.setenv("OPENAI_API_KEY", "okey")
    monkeypatch.delenv("WEBAPP_APP_NAME", raising=False)
    monkeypatch.delenv("WEBAPP_PORT", raising=False)
    s = Settings.from_env()
    assert s.webapp_app_name == ""
    assert s.webapp_port == 8080
    monkeypatch.setenv("WEBAPP_APP_NAME", "meucanvas")
    monkeypatch.setenv("WEBAPP_PORT", "9000")
    s2 = Settings.from_env()
    assert s2.webapp_app_name == "meucanvas"
    assert s2.webapp_port == 9000
```

Append to `tests/test_storage.py`:

```python
def test_get_project_name_and_canvas_updated_at(storage):
    assert storage.get_project_name(999) == ""
    pid = storage.get_or_create_project(100, "Acme")
    assert storage.get_project_name(pid) == "Acme"
    assert storage.canvas_updated_at(pid) is None
    storage.upsert_block(pid, "customer_segments", "SMBs", [1])
    ts = storage.canvas_updated_at(pid)
    assert isinstance(ts, float) and ts > 0
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_config.py tests/test_storage.py -v -k "webapp or project_name"`
Expected: FAIL (`AttributeError: webapp_app_name` / `get_project_name`)

- [ ] **Step 3: Implement**

`config.py` — fields after the participation ones:

```python
    webapp_app_name: str = ""
    webapp_port: int = 8080
```

and in `from_env()`:

```python
            webapp_app_name=os.environ.get("WEBAPP_APP_NAME", ""),
            webapp_port=int(os.environ.get("WEBAPP_PORT", "8080")),
```

`storage.py` — first line of `init_schema` body (before `executescript`):

```python
        self.conn.execute("PRAGMA journal_mode=WAL")
```

and methods inside `Storage`:

```python
    def get_project_name(self, project_id: int) -> str:
        cur = self.conn.execute(
            "SELECT name FROM projects WHERE id = ?", (project_id,)
        )
        row = cur.fetchone()
        return row["name"] if row else ""

    def canvas_updated_at(self, project_id: int):
        cur = self.conn.execute(
            "SELECT MAX(updated_at) ts FROM canvas_blocks WHERE project_id = ?",
            (project_id,),
        )
        row = cur.fetchone()
        return float(row["ts"]) if row and row["ts"] is not None else None
```

`.env.example` — append:

```
# --- Mini App (canvas UI) ---
# Registre o app no BotFather (/newapp) apontando para sua URL HTTPS pública
WEBAPP_APP_NAME=
WEBAPP_PORT=8080
```

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/test_config.py tests/test_storage.py -v` — PASS; `pytest -q` (expect 119 passed).

- [ ] **Step 5: Commit**

```bash
git add src/concierge/config.py src/concierge/storage.py .env.example tests/test_config.py tests/test_storage.py
git commit -m "feat: webapp settings, WAL mode, and canvas metadata queries"
```

---

### Task 2: initData authentication

**Files:**
- Create: `src/concierge/webapp/__init__.py` (empty), `src/concierge/webapp/auth.py`
- Create: `tests/test_webapp_auth.py`

**Interfaces:**
- Produces:
  - `validate_init_data(init_data: str, bot_token: str, max_age: int = 3600, now: float | None = None) -> bool` — official Telegram algorithm: parse querystring, pop `hash`, data_check_string = sorted `k=v` joined by `\n`, secret = HMAC_SHA256(key=b"WebAppData", msg=bot_token), computed hexdigest compared with `hmac.compare_digest`; then `auth_date` freshness (`now - auth_date <= max_age`; `now` injectable for tests, defaults to `time.time()`).
  - `parse_init_data(init_data: str) -> dict` — plain decoded key→value dict (use only AFTER validation).

- [ ] **Step 1: Write the failing test** — create `tests/test_webapp_auth.py`:

```python
import hashlib
import hmac
from urllib.parse import urlencode

from concierge.webapp.auth import validate_init_data, parse_init_data

TOKEN = "123456:TEST-TOKEN"


def sign_init_data(params: dict, token: str = TOKEN) -> str:
    dcs = "\n".join(f"{k}={v}" for k, v in sorted(params.items()))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    h = hmac.new(secret, dcs.encode(), hashlib.sha256).hexdigest()
    return urlencode({**params, "hash": h})


def test_valid_init_data_passes():
    init = sign_init_data({"auth_date": "1000", "start_param": "-500",
                           "user": '{"id":42,"first_name":"Ana"}'})
    assert validate_init_data(init, TOKEN, now=1500) is True


def test_tampered_field_rejected():
    init = sign_init_data({"auth_date": "1000", "start_param": "-500"})
    tampered = init.replace("-500", "-999")
    assert validate_init_data(tampered, TOKEN, now=1500) is False


def test_wrong_token_rejected():
    init = sign_init_data({"auth_date": "1000"})
    assert validate_init_data(init, "outro:token", now=1500) is False


def test_stale_auth_date_rejected():
    init = sign_init_data({"auth_date": "1000"})
    assert validate_init_data(init, TOKEN, now=1000 + 3601) is False
    assert validate_init_data(init, TOKEN, now=1000 + 3599) is True


def test_missing_hash_or_garbage_rejected():
    assert validate_init_data("auth_date=1000", TOKEN, now=1500) is False
    assert validate_init_data("", TOKEN, now=1500) is False
    assert validate_init_data("%%%not-a-querystring", TOKEN, now=1500) is False


def test_parse_init_data_decodes():
    init = sign_init_data({"auth_date": "1000", "start_param": "-500"})
    fields = parse_init_data(init)
    assert fields["start_param"] == "-500"
    assert "hash" in fields
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_webapp_auth.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'concierge.webapp'`

- [ ] **Step 3: Implement** — create empty `src/concierge/webapp/__init__.py` and `src/concierge/webapp/auth.py`:

```python
import hashlib
import hmac
import time
from urllib.parse import parse_qsl


def parse_init_data(init_data: str) -> dict:
    try:
        return dict(parse_qsl(init_data, strict_parsing=True))
    except ValueError:
        return {}


def validate_init_data(init_data, bot_token, max_age=3600, now=None):
    fields = parse_init_data(init_data)
    received_hash = fields.pop("hash", None)
    if not received_hash:
        return False
    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    computed = hmac.new(secret, data_check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(computed, received_hash):
        return False
    try:
        auth_date = int(fields.get("auth_date", "0"))
    except ValueError:
        return False
    current = now if now is not None else time.time()
    return (current - auth_date) <= max_age
```

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/test_webapp_auth.py -v` — PASS (6 passed); `pytest -q` (expect 125 passed).

- [ ] **Step 5: Commit**

```bash
git add src/concierge/webapp/__init__.py src/concierge/webapp/auth.py tests/test_webapp_auth.py
git commit -m "feat: telegram initData validation for the mini app"
```

---

### Task 3: FastAPI server

**Files:**
- Create: `src/concierge/webapp/server.py`, `src/concierge/webapp/__main__.py`
- Create: `tests/test_webapp_server.py`

**Interfaces:**
- Consumes: `validate_init_data`/`parse_init_data` (Task 2), `Storage.get_project/get_project_name/get_blocks/items_by_status/canvas_updated_at` (Task 1 + existing), `Settings.telegram_token/webapp_port/db_path`.
- Produces:
  - `create_app(settings, storage=None) -> FastAPI` — when `storage is None`, opens `sqlite3.connect(settings.db_path, check_same_thread=False)` and builds `Storage` + `init_schema()` (idempotent; enables WAL).
  - `POST /api/canvas` — body `{"init_data": str}` (pydantic `CanvasRequest`). Flow: validate → 401; `start_param` → int chat_id else 400; `get_project` → 404; payload per Global Constraints; `sqlite3.OperationalError` → one retry → 503.
  - `GET /` → `static/index.html` (FileResponse).
  - `main()` → uvicorn on `0.0.0.0:settings.webapp_port`; `__main__.py` calls it.

- [ ] **Step 1: Write the failing test** — create `tests/test_webapp_server.py`:

```python
import sqlite3

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


def _init(chat_id, auth_date="1000"):
    return sign_init_data({"auth_date": auth_date, "start_param": str(chat_id)}, TOKEN)


def test_unauthorized_without_valid_init_data(client_and_storage):
    client, _ = client_and_storage
    r = client.post("/api/canvas", json={"init_data": "auth_date=1&hash=deadbeef"})
    assert r.status_code == 401


def test_400_when_start_param_missing(client_and_storage):
    client, _ = client_and_storage
    init = sign_init_data({"auth_date": "1000"}, TOKEN)
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


def test_index_served(client_and_storage):
    client, _ = client_and_storage
    r = client.get("/")
    assert r.status_code == 200
    assert "value_proposition" in r.text
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_webapp_server.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'concierge.webapp.server'`

- [ ] **Step 3: Implement** — create `src/concierge/webapp/server.py`:

```python
import sqlite3
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from concierge.models import ItemStatus
from concierge.storage import Storage
from concierge.webapp.auth import parse_init_data, validate_init_data

STATIC_DIR = Path(__file__).parent / "static"


class CanvasRequest(BaseModel):
    init_data: str


def _payload(storage, pid):
    blocks = [
        {"block_name": b["block_name"], "content": b["content"],
         "item_ids": b["source_items"]}
        for b in storage.get_blocks(pid)
    ]
    items = [
        {"id": i["id"], "type": i["type"], "content": i["content"],
         "status": i["status"]}
        for i in storage.items_by_status(pid, [ItemStatus.ACTIVE, ItemStatus.VALIDATED])
    ]
    return {
        "project": {
            "name": storage.get_project_name(pid),
            "updated_at": storage.canvas_updated_at(pid),
        },
        "blocks": blocks,
        "items": items,
    }


def create_app(settings, storage=None):
    if storage is None:
        conn = sqlite3.connect(settings.db_path, check_same_thread=False)
        storage = Storage(conn)
        storage.init_schema()
    app = FastAPI()

    @app.get("/")
    def index():
        return FileResponse(STATIC_DIR / "index.html")

    @app.post("/api/canvas")
    def canvas(body: CanvasRequest):
        if not validate_init_data(body.init_data, settings.telegram_token):
            raise HTTPException(status_code=401, detail="unauthorized")
        fields = parse_init_data(body.init_data)
        try:
            chat_id = int(fields.get("start_param", ""))
        except ValueError:
            raise HTTPException(status_code=400, detail="missing start_param")
        pid = storage.get_project(chat_id)
        if pid is None:
            raise HTTPException(status_code=404, detail="project not found")
        try:
            return _payload(storage, pid)
        except sqlite3.OperationalError:
            try:
                return _payload(storage, pid)
            except sqlite3.OperationalError:
                raise HTTPException(status_code=503, detail="database busy")

    return app


def main():
    import uvicorn

    from concierge.config import Settings

    settings = Settings.from_env()
    uvicorn.run(create_app(settings), host="0.0.0.0", port=settings.webapp_port)
```

Create `src/concierge/webapp/__main__.py`:

```python
from concierge.webapp.server import main

main()
```

NOTE for this task: `test_index_served` needs `static/index.html` to exist. Create a MINIMAL placeholder now (Task 4 replaces it with the real page) — `src/concierge/webapp/static/index.html`:

```html
<!DOCTYPE html>
<html><body>
value_proposition customer_segments channels customer_relationships
revenue_streams key_resources key_activities key_partnerships cost_structure
</body></html>
```

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/test_webapp_server.py -v` — PASS (6 passed); `pytest -q` (expect 131 passed).

- [ ] **Step 5: Commit**

```bash
git add src/concierge/webapp/server.py src/concierge/webapp/__main__.py src/concierge/webapp/static/index.html tests/test_webapp_server.py
git commit -m "feat: fastapi mini app server with validated canvas API"
```

---

### Task 4: Frontend — the Mini App page

**Files:**
- Replace: `src/concierge/webapp/static/index.html` (the Task 3 placeholder)
- Modify: `tests/test_webapp_server.py` (strengthen the static test)

**Interfaces:**
- Consumes: `POST /api/canvas` payload (Task 3), Telegram WebApp JS API.
- Produces: single-page app — BMC 9-block grid (canonical layout via CSS grid areas; single column under 480px), Telegram theme vars, loading/empty/error states, bottom sheet on block tap showing the strategic items (when `item_ids` empty — the common case today — the sheet lists the whole strategic base under "Base estratégica").

- [ ] **Step 1: Strengthen the static test** — in `tests/test_webapp_server.py`, replace `test_index_served` with:

```python
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
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_webapp_server.py::test_index_served_with_full_grid -v`
Expected: FAIL (placeholder lacks `telegram-web-app.js`)

- [ ] **Step 3: Replace `src/concierge/webapp/static/index.html`** with the full page:

```html
<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Canvas Estratégico</title>
<script src="https://telegram.org/js/telegram-web-app.js"></script>
<style>
  :root{
    --bg:#ffffff; --ink:#0f1419; --muted:#6b7785; --card:#f3f5f7;
    --line:#dfe4e8; --accent:#2481cc; --ok:#2e9e5b;
  }
  *{box-sizing:border-box;margin:0;padding:0}
  body{background:var(--bg);color:var(--ink);
    font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
    padding:12px;padding-bottom:80px}
  header{margin-bottom:12px}
  header h1{font-size:1.1rem}
  header small{color:var(--muted)}
  #state{color:var(--muted);padding:24px 4px;text-align:center}
  #grid{display:grid;gap:8px;
    grid-template-columns:repeat(10,1fr);
    grid-template-areas:
      "kp kp ka ka vp vp cr cr cs cs"
      "kp kp kr kr vp vp ch ch cs cs"
      "co co co co co re re re re re"}
  .block{background:var(--card);border:1px solid var(--line);border-radius:10px;
    padding:10px;min-height:96px;cursor:pointer}
  .block h2{font-size:.72rem;text-transform:uppercase;letter-spacing:.04em;
    color:var(--accent);margin-bottom:6px}
  .block p{font-size:.8rem;line-height:1.35;color:var(--ink);
    display:-webkit-box;-webkit-line-clamp:5;-webkit-box-orient:vertical;overflow:hidden}
  .block.empty p{color:var(--muted);font-style:italic}
  [data-b="key_partnerships"]{grid-area:kp}
  [data-b="key_activities"]{grid-area:ka}
  [data-b="key_resources"]{grid-area:kr}
  [data-b="value_proposition"]{grid-area:vp}
  [data-b="customer_relationships"]{grid-area:cr}
  [data-b="channels"]{grid-area:ch}
  [data-b="customer_segments"]{grid-area:cs}
  [data-b="cost_structure"]{grid-area:co}
  [data-b="revenue_streams"]{grid-area:re}
  @media (max-width:480px){
    #grid{grid-template-columns:1fr;grid-template-areas:
      "vp" "cs" "kp" "ka" "kr" "cr" "ch" "re" "co"}
  }
  #sheet{position:fixed;left:0;right:0;bottom:-100%;max-height:70vh;overflow:auto;
    background:var(--bg);border-top:2px solid var(--accent);
    border-radius:16px 16px 0 0;padding:16px;transition:bottom .25s ease;
    box-shadow:0 -8px 30px rgba(0,0,0,.18)}
  #sheet.open{bottom:0}
  #sheet h3{font-size:.95rem;margin-bottom:8px}
  #sheet .content{font-size:.85rem;line-height:1.4;margin-bottom:12px}
  .item{display:flex;gap:8px;align-items:flex-start;padding:8px 0;
    border-top:1px solid var(--line);font-size:.82rem}
  .chip{flex:none;font-size:.68rem;padding:2px 8px;border-radius:999px;
    border:1px solid var(--line);color:var(--muted)}
  .chip.validated{border-color:var(--ok);color:var(--ok)}
  .chip.active{border-color:var(--accent);color:var(--accent)}
  #close{float:right;background:none;border:none;font-size:1.2rem;
    color:var(--muted);cursor:pointer}
</style>
</head>
<body>
<header>
  <h1 id="pname">Canvas Estratégico</h1>
  <small id="updated"></small>
</header>
<div id="state">Carregando…</div>
<div id="grid" hidden></div>
<div id="sheet">
  <button id="close">✕</button>
  <h3 id="sheet-title"></h3>
  <div class="content" id="sheet-content"></div>
  <div id="sheet-items"></div>
</div>
<script>
  const LABELS = {
    key_partnerships: "Parcerias-chave", key_activities: "Atividades-chave",
    key_resources: "Recursos-chave", value_proposition: "Proposta de valor",
    customer_relationships: "Relacionamento", channels: "Canais",
    customer_segments: "Segmentos de clientes", cost_structure: "Estrutura de custos",
    revenue_streams: "Fontes de receita",
  };
  const ORDER = ["key_partnerships","key_activities","key_resources",
    "value_proposition","customer_relationships","channels",
    "customer_segments","cost_structure","revenue_streams"];
  const tg = window.Telegram && window.Telegram.WebApp;
  if (tg) {
    tg.ready(); tg.expand();
    const t = tg.themeParams || {};
    const map = {bg_color:"--bg", text_color:"--ink", hint_color:"--muted",
                 secondary_bg_color:"--card", button_color:"--accent"};
    for (const [k, v] of Object.entries(map))
      if (t[k]) document.documentElement.style.setProperty(v, t[k]);
  }
  const state = document.getElementById("state");
  const grid = document.getElementById("grid");
  let DATA = null;

  function openSheet(block) {
    document.getElementById("sheet-title").textContent = LABELS[block.block_name];
    document.getElementById("sheet-content").textContent =
      block.content || "Bloco ainda vazio.";
    const box = document.getElementById("sheet-items");
    box.innerHTML = "";
    const ids = block.item_ids || [];
    let items = DATA.items.filter(i => ids.includes(i.id));
    let title = "Itens que sustentam este bloco";
    if (!items.length) { items = DATA.items; title = "Base estratégica"; }
    if (items.length) {
      const h = document.createElement("h3"); h.textContent = title;
      box.appendChild(h);
      for (const i of items) {
        const d = document.createElement("div"); d.className = "item";
        d.innerHTML = `<span class="chip ${i.status}">${i.status}</span>` +
                      `<span><b>${i.type}</b> — ${i.content}</span>`;
        box.appendChild(d);
      }
    }
    document.getElementById("sheet").classList.add("open");
  }
  document.getElementById("close").onclick = () =>
    document.getElementById("sheet").classList.remove("open");

  function render(data) {
    DATA = data;
    document.getElementById("pname").textContent =
      data.project.name || "Canvas Estratégico";
    if (data.project.updated_at)
      document.getElementById("updated").textContent =
        "atualizado em " + new Date(data.project.updated_at * 1000).toLocaleString();
    const byName = Object.fromEntries(data.blocks.map(b => [b.block_name, b]));
    grid.innerHTML = "";
    for (const name of ORDER) {
      const b = byName[name] || {block_name: name, content: "", item_ids: []};
      const el = document.createElement("div");
      el.className = "block" + (b.content ? "" : " empty");
      el.dataset.b = name;
      el.innerHTML = `<h2>${LABELS[name]}</h2><p>${b.content ||
        "ainda em construção"}</p>`;
      el.onclick = () => openSheet(b);
      grid.appendChild(el);
    }
    if (!data.blocks.length)
      state.textContent = "Canvas ainda em construção — continue a conversa no grupo.";
    else state.hidden = true;
    grid.hidden = false;
  }

  async function load() {
    if (!tg || !tg.initData) {
      state.textContent = "Abra pelo botão do bot no Telegram.";
      return;
    }
    try {
      const r = await fetch("/api/canvas", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({init_data: tg.initData}),
      });
      if (r.status === 401) { state.textContent = "Abra pelo botão do bot no Telegram."; return; }
      if (r.status === 404) { state.textContent = "Projeto não encontrado — rode /start no grupo."; return; }
      if (!r.ok) { state.textContent = "Erro ao carregar. Tente novamente."; return; }
      render(await r.json());
    } catch (e) {
      state.textContent = "Erro de rede. Tente novamente.";
    }
  }
  load();
</script>
</body>
</html>
```

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/test_webapp_server.py -v` — PASS; `pytest -q` (expect 131 passed).

- [ ] **Step 5: Commit**

```bash
git add src/concierge/webapp/static/index.html tests/test_webapp_server.py
git commit -m "feat: mini app canvas page with BMC grid and item drill-down"
```

---

### Task 5: /canvas command, requirements, docs

**Files:**
- Modify: `src/concierge/bot.py`, `requirements.txt`, `README.md`, `SETUP.md`
- Modify: `tests/test_bot.py`

**Interfaces:**
- Consumes: `Settings.webapp_app_name` (via `orchestrator.settings`).
- Produces: `handle_canvas(orchestrator, chat_id, bot_username) -> tuple[str, str | None]` — returns `(reply_text, url_or_None)`. Gate `/start` → `(NOT_STARTED, None)`; `webapp_app_name` empty → friendly config message, `None`; else `("📋 Abra o canvas do projeto:", f"https://t.me/{bot_username}/{app_name}?startapp={chat_id}")`. Async closure sends the URL as an `InlineKeyboardButton(url=...)` when present; plain text otherwise. Registration `CommandHandler("canvas", canvas)`.

- [ ] **Step 1: Write the failing test** — append to `tests/test_bot.py`:

```python
def test_handle_canvas_builds_direct_link(fake_llm):
    o = _orch(fake_llm)
    o.storage.get_or_create_project(100, "Acme")
    o.settings.webapp_app_name = "meucanvas"
    text, url = bot.handle_canvas(o, 100, "meu_bot")
    assert url == "https://t.me/meu_bot/meucanvas?startapp=100"
    assert "canvas" in text.lower()


def test_handle_canvas_gates(fake_llm):
    o = _orch(fake_llm)
    # sem /start
    text, url = bot.handle_canvas(o, 777, "meu_bot")
    assert text == bot.NOT_STARTED and url is None
    # sem app name configurado
    o.storage.get_or_create_project(100, "Acme")
    o.settings.webapp_app_name = ""
    text, url = bot.handle_canvas(o, 100, "meu_bot")
    assert url is None and "WEBAPP_APP_NAME" in text
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_bot.py -v -k handle_canvas`
Expected: FAIL with `AttributeError: module 'concierge.bot' has no attribute 'handle_canvas'`

- [ ] **Step 3: Implement** — in `src/concierge/bot.py`:

3a. Extend the telegram import line to include the keyboard types:

```python
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
```

3b. Pure handler (after `handle_personality`):

```python
def handle_canvas(orchestrator, chat_id, bot_username):
    pid = orchestrator.storage.get_project(chat_id)
    if pid is None:
        return NOT_STARTED, None
    app_name = orchestrator.settings.webapp_app_name
    if not app_name:
        return (
            "O Mini App do canvas não está configurado. Registre o app no "
            "BotFather (/newapp) e defina WEBAPP_APP_NAME no .env.",
            None,
        )
    url = f"https://t.me/{bot_username}/{app_name}?startapp={chat_id}"
    return "📋 Abra o canvas do projeto:", url
```

3c. Async closure inside `build_application` + registration:

```python
    async def canvas(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        text, url = handle_canvas(
            orchestrator, update.effective_chat.id, ctx.bot.username
        )
        if url:
            keyboard = InlineKeyboardMarkup(
                [[InlineKeyboardButton(text="📋 Abrir Canvas", url=url)]]
            )
            await update.message.reply_text(text, reply_markup=keyboard)
        else:
            await update.message.reply_text(text)
```

```python
    app.add_handler(CommandHandler("canvas", canvas))
```

3d. `requirements.txt` — append:

```
fastapi==0.139.0
uvicorn==0.49.0
httpx==0.28.1
```

- [ ] **Step 4: Run to verify pass + smoke**

Run: `pytest tests/test_bot.py -v` then `pytest -q` (expect 133 passed).
Run: `PYTHONPATH=src python -c "from concierge.webapp.server import create_app, main; from concierge.bot import handle_canvas; print('ok')"` — expect `ok`.

- [ ] **Step 5: Update docs**

`README.md` — commands list: add `- /canvas — abre o Mini App com o Business Model Canvas visual`. After the Participation section add:

```markdown
## Canvas Mini App

Run the web app alongside the bot and expose it via an HTTPS tunnel:

    PYTHONPATH=src python -m concierge.webapp        # serves on WEBAPP_PORT (8080)
    cloudflared tunnel --url http://localhost:8080   # public HTTPS URL

Register the Mini App with @BotFather (`/newapp`, pick a short name, set the
tunnel URL) and put the short name in `WEBAPP_APP_NAME`. Then `/canvas` in the
group posts a button that opens the live canvas inside Telegram.
```

`SETUP.md` — command table: add `| /canvas | botão que abre o Mini App com o canvas visual |`. New section after §7:

```markdown
## 7.1 Mini App do canvas (opcional)

1. Rode o servidor: `PYTHONPATH=src python -m concierge.webapp` (porta `WEBAPP_PORT`, default 8080).
2. Exponha via túnel: `cloudflared tunnel --url http://localhost:8080` — copie a URL HTTPS.
3. No @BotFather: `/newapp` → escolha o bot → defina título/short name → cole a URL do túnel.
   (Se a URL do túnel mudar, atualize em /myapps → Edit Web App URL.)
4. `WEBAPP_APP_NAME=<short name>` no `.env` e reinicie o bot.
5. No grupo: `/canvas` → botão "📋 Abrir Canvas" abre a grade do BMC dentro do Telegram;
   toque num bloco para ver os itens estratégicos.
```

- [ ] **Step 6: Commit**

```bash
git add src/concierge/bot.py requirements.txt tests/test_bot.py README.md SETUP.md
git commit -m "feat: /canvas command with direct-link mini app button"
```

---

## Self-Review

**Spec coverage (incl. adendo):** §1 proposta/grade/drill-down/tema → T4; §2 processo separado + WAL + config → T1/T3; §3.1 auth → T2, server → T3, static → T4; §3.2 payload → T3 (`_payload` + testes); §3.3 bot/config/storage → T5/T1; §4 segurança (401, 1h, read-only, chat_id assinado via start_param per adendo) → T2/T3; §5 erros (401/404/400/503/vazio) → T3; §6 testes → T2/T3/T4; §7 roteiro → T5 docs; §8 deps → T5; adendo (direct link + WEBAPP_APP_NAME) → T1/T5. ✓

**Placeholders:** nenhum — o placeholder de HTML do T3 é um artefato de sequência declarado e substituído no T4. ✓

**Type consistency:** `create_app(settings, storage=None)`; `sign_init_data` importado de `tests.test_webapp_auth` no T3 (mesmo módulo de teste); `handle_canvas -> (str, str|None)` consistente entre teste e closure; payload keys idênticas em T3 e no JS do T4 (`project.name/updated_at`, `blocks[].block_name/content/item_ids`, `items[].id/type/content/status`). ✓

**Notas conscientes:** (1) drill-down por bloco degrada para "Base estratégica" quando `item_ids` está vazio — consequência do M3 (source_items não populado), documentada; (2) `test_index_served` do T3 é substituído no T4 pela versão completa.
