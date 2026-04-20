import aiosqlite
import json
import logging

logger = logging.getLogger(__name__)
DB_PATH = "antiflood.db"


async def init_recurring_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS recurring_messages (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id         INTEGER NOT NULL,
                enabled         INTEGER DEFAULT 1,
                text            TEXT DEFAULT '',
                media_file_id   TEXT DEFAULT '',
                media_type      TEXT DEFAULT '',
                url_buttons     TEXT DEFAULT '[]',
                start_time      TEXT DEFAULT '09:00',
                end_time        TEXT DEFAULT '23:00',
                interval_hours  INTEGER DEFAULT 6,
                delete_previous INTEGER DEFAULT 0,
                last_message_id INTEGER DEFAULT 0,
                next_send_at    REAL DEFAULT 0
            )
        """)
        await db.commit()


async def get_recurring_messages(chat_id: int) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM recurring_messages WHERE chat_id = ? ORDER BY id",
            (chat_id,)
        ) as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]


async def get_recurring_message(msg_id: int) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM recurring_messages WHERE id = ?", (msg_id,)
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def create_recurring_message(chat_id: int) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "INSERT INTO recurring_messages (chat_id) VALUES (?)", (chat_id,)
        )
        await db.commit()
        return cur.lastrowid


async def update_recurring_message(msg_id: int, **kwargs):
    if not kwargs:
        return
    fields = ", ".join(f"{k} = ?" for k in kwargs)
    values = list(kwargs.values()) + [msg_id]
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            f"UPDATE recurring_messages SET {fields} WHERE id = ?", values
        )
        await db.commit()


async def delete_recurring_message(msg_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM recurring_messages WHERE id = ?", (msg_id,))
        await db.commit()


async def get_all_pending_messages() -> list[dict]:
    import time
    now = time.time()
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM recurring_messages WHERE enabled = 1 AND next_send_at <= ? AND next_send_at > 0",
            (now,)
        ) as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]
