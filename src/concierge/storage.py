import sqlite3
from concierge.models import ProjectMode

SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_chat_id INTEGER UNIQUE NOT NULL,
    name TEXT NOT NULL,
    framework_type TEXT NOT NULL DEFAULT 'bmc',
    mode TEXT NOT NULL DEFAULT 'moderate',
    created_at REAL NOT NULL DEFAULT (strftime('%s','now'))
);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL,
    telegram_msg_id INTEGER NOT NULL,
    author TEXT NOT NULL,
    text TEXT NOT NULL,
    ts REAL NOT NULL,
    processed INTEGER NOT NULL DEFAULT 0,
    UNIQUE(project_id, telegram_msg_id)
);
CREATE TABLE IF NOT EXISTS strategic_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL,
    type TEXT NOT NULL,
    content TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    confidence REAL NOT NULL DEFAULT 0.0,
    source_message_id INTEGER,
    created_at REAL NOT NULL DEFAULT (strftime('%s','now')),
    updated_at REAL NOT NULL DEFAULT (strftime('%s','now')),
    superseded_by INTEGER
);
CREATE TABLE IF NOT EXISTS canvas_blocks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL,
    block_name TEXT NOT NULL,
    content TEXT NOT NULL DEFAULT '',
    updated_at REAL NOT NULL DEFAULT (strftime('%s','now')),
    source_items TEXT NOT NULL DEFAULT '[]',
    UNIQUE(project_id, block_name)
);
CREATE TABLE IF NOT EXISTS interventions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL,
    message_id INTEGER,
    item_id INTEGER,
    reason TEXT NOT NULL,
    confidence REAL NOT NULL,
    sent_at REAL NOT NULL DEFAULT (strftime('%s','now'))
);
CREATE TABLE IF NOT EXISTS knowledge_docs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL,
    filename TEXT NOT NULL,
    uploaded_at REAL NOT NULL DEFAULT (strftime('%s','now')),
    chunk_count INTEGER NOT NULL DEFAULT 0
);
"""


class Storage:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.conn.row_factory = sqlite3.Row

    def init_schema(self) -> None:
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def get_or_create_project(self, chat_id: int, name: str) -> int:
        self.conn.execute(
            "INSERT OR IGNORE INTO projects (telegram_chat_id, name) VALUES (?, ?)",
            (chat_id, name),
        )
        self.conn.commit()
        cur = self.conn.execute(
            "SELECT id FROM projects WHERE telegram_chat_id = ?", (chat_id,)
        )
        return cur.fetchone()["id"]

    def add_message(self, project_id: int, telegram_msg_id: int, author: str, text: str, ts: float) -> int | None:
        try:
            cur = self.conn.execute(
                "INSERT INTO messages (project_id, telegram_msg_id, author, text, ts) "
                "VALUES (?, ?, ?, ?, ?)",
                (project_id, telegram_msg_id, author, text, ts),
            )
            self.conn.commit()
            return cur.lastrowid
        except sqlite3.IntegrityError:
            return None

    def unprocessed_messages(self, project_id: int) -> list[dict]:
        cur = self.conn.execute(
            "SELECT id, author, text, ts FROM messages "
            "WHERE project_id = ? AND processed = 0 ORDER BY ts",
            (project_id,),
        )
        return [dict(r) for r in cur.fetchall()]

    def mark_processed(self, message_ids: list[int]) -> None:
        self.conn.executemany(
            "UPDATE messages SET processed = 1 WHERE id = ?",
            [(mid,) for mid in message_ids],
        )
        self.conn.commit()

    def set_mode(self, project_id: int, mode: ProjectMode) -> None:
        self.conn.execute(
            "UPDATE projects SET mode = ? WHERE id = ?", (mode.value, project_id)
        )
        self.conn.commit()

    def get_mode(self, project_id: int) -> ProjectMode:
        cur = self.conn.execute(
            "SELECT mode FROM projects WHERE id = ?", (project_id,)
        )
        return ProjectMode(cur.fetchone()["mode"])
