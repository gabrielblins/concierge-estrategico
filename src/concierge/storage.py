import sqlite3
from concierge.models import ProjectMode, ItemType, ItemStatus

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

    def add_item(self, project_id, type, content, confidence,
                 source_message_id, status=ItemStatus.ACTIVE):
        cur = self.conn.execute(
            "INSERT INTO strategic_items "
            "(project_id, type, content, status, confidence, source_message_id) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (project_id, type.value, content, status.value, confidence, source_message_id),
        )
        self.conn.commit()
        return cur.lastrowid

    def items_by_status(self, project_id, statuses):
        placeholders = ",".join("?" for _ in statuses)
        params = [project_id] + [s.value for s in statuses]
        cur = self.conn.execute(
            f"SELECT id, type, content, status, confidence, source_message_id "
            f"FROM strategic_items WHERE project_id = ? AND status IN ({placeholders})",
            params,
        )
        return [dict(r) for r in cur.fetchall()]

    def supersede_item(self, old_item_id, new_item_id):
        self.conn.execute(
            "UPDATE strategic_items SET status = 'superseded', superseded_by = ?, "
            "updated_at = strftime('%s','now') WHERE id = ?",
            (new_item_id, old_item_id),
        )
        self.conn.commit()

    def set_item_status(self, item_id, status):
        self.conn.execute(
            "UPDATE strategic_items SET status = ?, updated_at = strftime('%s','now') "
            "WHERE id = ?",
            (status.value, item_id),
        )
        self.conn.commit()

    def add_intervention(self, project_id, message_id, item_id, reason, confidence):
        cur = self.conn.execute(
            "INSERT INTO interventions (project_id, message_id, item_id, reason, confidence) "
            "VALUES (?, ?, ?, ?, ?)",
            (project_id, message_id, item_id, reason, confidence),
        )
        self.conn.commit()
        return cur.lastrowid

    def last_intervention(self, project_id):
        cur = self.conn.execute(
            "SELECT reason, confidence, item_id, message_id, sent_at "
            "FROM interventions WHERE project_id = ? ORDER BY sent_at DESC, id DESC LIMIT 1",
            (project_id,),
        )
        row = cur.fetchone()
        return dict(row) if row else None
