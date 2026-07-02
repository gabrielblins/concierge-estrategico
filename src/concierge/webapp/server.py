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
        # no-store: o webview do Telegram cacheia agressivamente; a página
        # precisa refletir atualizações do bot sem exigir limpar cache.
        return FileResponse(
            STATIC_DIR / "index.html", headers={"Cache-Control": "no-store"}
        )

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
