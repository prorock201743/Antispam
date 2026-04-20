import aiosqlite
import json
import logging
import os
from config import DEFAULT_SETTINGS

logger = logging.getLogger(__name__)
DB_PATH = os.path.join(os.getenv("DATA_DIR", "/app/data"), "antiflood.db")

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        # Настройки групп
        await db.execute("""
            CREATE TABLE IF NOT EXISTS group_settings (
                chat_id     INTEGER PRIMARY KEY,
                chat_title  TEXT,
                settings    TEXT NOT NULL
            )
        """)
        # Счётчик сообщений пользователей
        await db.execute("""
            CREATE TABLE IF NOT EXISTS message_counts (
                chat_id     INTEGER NOT NULL,
                user_id     INTEGER NOT NULL,
                count       INTEGER DEFAULT 0,
                window_start REAL DEFAULT 0,
                violations  INTEGER DEFAULT 0,
                last_msg_link    TEXT DEFAULT '',
                PRIMARY KEY (chat_id, user_id)
            )
        """)
        await db.commit()
    logger.info("База данных инициализирована")


async def get_settings(chat_id: int) -> dict:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT settings FROM group_settings WHERE chat_id = ?", (chat_id,)
        ) as cur:
            row = await cur.fetchone()
            if row:
                return {**DEFAULT_SETTINGS, **json.loads(row[0])}
            return dict(DEFAULT_SETTINGS)


async def save_settings(chat_id: int, chat_title: str, settings: dict):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO group_settings (chat_id, chat_title, settings)
            VALUES (?, ?, ?)
            ON CONFLICT(chat_id) DO UPDATE SET
                chat_title = excluded.chat_title,
                settings   = excluded.settings
        """, (chat_id, chat_title, json.dumps(settings)))
        await db.commit()


async def update_setting(chat_id: int, chat_title: str, key: str, value):
    settings = await get_settings(chat_id)
    settings[key] = value
    await save_settings(chat_id, chat_title, settings)


async def get_message_count(chat_id: int, user_id: int) -> tuple[int, float, int, str]:
    """Возвращает (count, window_start, violations, last_msg_link)"""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT count, window_start, violations, last_msg_link FROM message_counts WHERE chat_id=? AND user_id=?",
            (chat_id, user_id)
        ) as cur:
            row = await cur.fetchone()
            return row if row else (0, 0.0, 0, "")


async def set_message_count(chat_id: int, user_id: int, count: int, window_start: float, violations: int, last_msg_link: str = ""):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO message_counts (chat_id, user_id, count, window_start, violations, last_msg_link)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(chat_id, user_id) DO UPDATE SET
                count         = excluded.count,
                window_start  = excluded.window_start,
                violations    = excluded.violations,
                last_msg_link = excluded.last_msg_link
        """, (chat_id, user_id, count, window_start, violations, last_msg_link))
        await db.commit()


async def reset_violations(chat_id: int, user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE message_counts SET violations=0, count=0 WHERE chat_id=? AND user_id=?",
            (chat_id, user_id)
        )
        await db.commit()


async def get_all_groups() -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT chat_id, chat_title, settings FROM group_settings"
        ) as cur:
            rows = await cur.fetchall()
            result = []
            for row in rows:
                result.append({
                    "chat_id": row[0],
                    "chat_title": row[1],
                    "settings": {**DEFAULT_SETTINGS, **json.loads(row[2])}
                })
            return result

async def remove_group(chat_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM group_settings WHERE chat_id = ?", (chat_id,))
        await db.commit()
