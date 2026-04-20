import asyncio
import time
import logging
import json
from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from bot.database.recurring_db import get_all_pending_messages, update_recurring_message

logger = logging.getLogger(__name__)


async def send_recurring_message(bot: Bot, msg: dict):
    from datetime import datetime, timezone, timedelta

    # Проверяем временное окно
    now_msk = datetime.now(timezone(timedelta(hours=3)))
    try:
        sh, sm = map(int, msg["start_time"].split(":"))
        eh, em = map(int, msg["end_time"].split(":"))
        start_minutes = sh * 60 + sm
        end_minutes = eh * 60 + em
        now_minutes = now_msk.hour * 60 + now_msk.minute
        if not (start_minutes <= now_minutes <= end_minutes):
            await update_recurring_message(
                msg["id"],
                next_send_at=time.time() + msg["interval_hours"] * 3600
            )
            return
    except Exception:
        pass

    chat_id = msg["chat_id"]
    text = msg["text"] or ""
    media_file_id = msg["media_file_id"] or ""
    media_type = msg["media_type"] or ""
    delete_previous = bool(msg["delete_previous"])
    last_message_id = msg["last_message_id"]
    interval_hours = msg["interval_hours"]
    url_buttons_raw = msg["url_buttons"] or "[]"

    reply_markup = None
    try:
        buttons_data = json.loads(url_buttons_raw)
        if buttons_data:
            reply_markup = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=b["text"], url=b["url"])]
                for b in buttons_data if b.get("text") and b.get("url")
            ])
    except Exception:
        pass

    if delete_previous and last_message_id:
        try:
            await bot.delete_message(chat_id, last_message_id)
        except Exception:
            pass

    sent = None
    try:
        if media_file_id and media_type == "photo":
            sent = await bot.send_photo(
                chat_id, photo=media_file_id,
                caption=text or None, reply_markup=reply_markup
            )
        elif media_file_id and media_type == "video":
            sent = await bot.send_video(
                chat_id, video=media_file_id,
                caption=text or None, reply_markup=reply_markup
            )
        elif text:
            sent = await bot.send_message(
                chat_id, text=text,
                reply_markup=reply_markup
            )
    except Exception as e:
        logger.error(f"Ошибка отправки повторяющегося сообщения {msg['id']}: {e}")
        await update_recurring_message(
            msg["id"],
            next_send_at=time.time() + interval_hours * 3600
        )
        return

    await update_recurring_message(
        msg["id"],
        last_message_id=sent.message_id if sent else 0,
        next_send_at=time.time() + interval_hours * 3600
    )
    logger.info(f"Отправлено повторяющееся сообщение {msg['id']} в чат {chat_id}")


async def scheduler_loop(bot: Bot):
    logger.info("Планировщик запущен")
    while True:
        try:
            pending = await get_all_pending_messages()
            for msg in pending:
                asyncio.create_task(send_recurring_message(bot, msg))
        except Exception as e:
            logger.error(f"Ошибка планировщика: {e}")
        await asyncio.sleep(30)