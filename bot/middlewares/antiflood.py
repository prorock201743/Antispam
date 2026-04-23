import asyncio
import time
import logging
from datetime import timezone, timedelta
from typing import Any, Callable, Awaitable
from aiogram import BaseMiddleware
from aiogram.types import Message, ChatPermissions
from bot.database.db import (
    get_settings, get_message_count, set_message_count
)

logger = logging.getLogger(__name__)


class AntiFloodMiddleware(BaseMiddleware):

    async def __call__(
        self,
        handler: Callable[[Message, dict[str, Any]], Awaitable[Any]],
        event: Message,
        data: dict[str, Any],
    ) -> Any:
        if not event.chat or event.chat.type not in ("group", "supergroup"):
            return await handler(event, data)

        chat_id = event.chat.id
        user_id = event.from_user.id if event.from_user else None

        if not user_id:
            return await handler(event, data)

        settings = await get_settings(chat_id)

        if not settings.get("enabled", True):
            return await handler(event, data)

        whitelist = settings.get("whitelist", [])
        if user_id in whitelist:
            return await handler(event, data)

        bot = data.get("bot")
        if bot:
            try:
                member = await bot.get_chat_member(chat_id, user_id)
                if member.status in ("administrator", "creator"):
                    return await handler(event, data)
            except Exception:
                pass

        # Проверяем запрещённые фразы
        msg_text = event.text or event.caption or ""
        if msg_text:
            banned_phrases = settings.get("banned_phrases", [])
            msg_lower = msg_text.lower()
            for phrase in banned_phrases:
                if phrase in msg_lower:
                    try:
                        await event.delete()
                    except Exception:
                        pass
                    return

        now = time.time()
        interval = settings["interval"]
        max_messages = settings["max_messages"]

        count, window_start, violations, last_msg_link = await get_message_count(chat_id, user_id)

        if now - window_start > interval:
            count = 0
            window_start = now
            last_msg_link = ""

        count += 1

        if count == max_messages:
            pure_id = str(chat_id).replace("-100", "")
            last_msg_link = f"https://t.me/c/{pure_id}/{event.message_id}"

        await set_message_count(chat_id, user_id, count, window_start, violations, last_msg_link)

        if count > max_messages:
            await self._apply_restriction(event, data, settings, violations, last_msg_link)
            return

        return await handler(event, data)

    async def _apply_restriction(
        self,
        message: Message,
        data: dict,
        settings: dict,
        violations: int,
        last_msg_link: str = "",
    ):
        bot = data.get("bot")
        if not bot:
            return

        chat_id = message.chat.id
        user_id = message.from_user.id
        user_name = message.from_user.full_name
        username = f"@{message.from_user.username}" if message.from_user.username else user_name

        mode = settings.get("restriction_mode", "mute")
        mute_duration = settings.get("mute_duration", 86400)
        auto_delete = settings.get("auto_delete_bot_msgs", True)
        delete_delay = settings.get("auto_delete_delay", 180)

        new_violations = violations + 1
        count, window_start, _, __ = await get_message_count(chat_id, user_id)
        await set_message_count(chat_id, user_id, count, window_start, new_violations, last_msg_link)

        msg_time = message.date

        try:
            await message.delete()
        except Exception as e:
            logger.warning(f"Не удалось удалить сообщение: {e}")

        max_warnings = 3

        if new_violations <= max_warnings:
            time_left = int(window_start + settings["interval"] - time.time())
            warn_text = (
                f"⚠️ <b>Предупреждение {new_violations}/{max_warnings} — {username}!</b>\n"
                f"В группе разрешено не более <b>{settings['max_messages']}</b> "
                f"сообщений за <b>{_format_seconds(settings['interval'])}</b>.\n"
                f"<a href='{last_msg_link}'>Последнее разрешённое сообщение</a> отправлено в "
                f"<b>{msg_time.astimezone(timezone(timedelta(hours=3))).strftime('%H:%M:%S')} (МСК)</b>\n"
                f"Следующее можно отправить через <b>{_format_seconds(time_left)}</b>.\n"
                f"После {max_warnings} предупреждений последует ограничение."
            )
            try:
                sent = await message.answer(warn_text)
                if auto_delete:
                    asyncio.create_task(_delete_after(bot, chat_id, sent.message_id, delete_delay))
            except Exception as e:
                logger.warning(f"Не удалось отправить предупреждение: {e}")
            return

        until_date = int(time.time()) + mute_duration
        warn_text = ""

        try:
            if mode == "ban":
                await bot.ban_chat_member(chat_id, user_id)
                warn_text = (
                    f"🚫 <b>Пользователь {username} заблокирован</b>\n"
                    f"Причина: превышен лимит сообщений ({settings['max_messages']} "
                    f"за {_format_seconds(settings['interval'])})"
                )
            elif mode == "kick":
                await bot.ban_chat_member(chat_id, user_id)
                await asyncio.sleep(1)
                await bot.unban_chat_member(chat_id, user_id)
                warn_text = (
                    f"👟 <b>Пользователь {username} исключён из группы</b>\n"
                    f"Причина: превышен лимит сообщений"
                )
            else:  # mute
                await bot.restrict_chat_member(
                    chat_id, user_id,
                    permissions=ChatPermissions(can_send_messages=False),
                    until_date=until_date,
                )
                warn_text = (
                    f"🔇 <b>{username} отдохни, амиго!</b>\n"
                    f"Получено {max_warnings} предупреждения за превышение лимита.\n"
                    f"Мут выдан на <b>{_format_seconds(mute_duration)}</b>."
                )
        except Exception as e:
            logger.error(f"Ошибка применения ограничения: {e}")
            return

        try:
            sent = await message.answer(warn_text)
            if auto_delete:
                asyncio.create_task(_delete_after(bot, chat_id, sent.message_id, delete_delay))
        except Exception as e:
            logger.warning(f"Не удалось отправить сообщение об ограничении: {e}")


async def _delete_after(bot, chat_id: int, message_id: int, delay: int):
    await asyncio.sleep(delay)
    try:
        await bot.delete_message(chat_id, message_id)
    except Exception:
        pass


def _format_seconds(seconds: int) -> str:
    if seconds < 60:
        return f"{seconds} сек."
    elif seconds < 3600:
        return f"{seconds // 60} мин."
    elif seconds < 86400:
        return f"{seconds // 3600} ч."
    else:
        days = seconds // 86400
        return f"{days} сут." if days != 1 else "1 сутки"
