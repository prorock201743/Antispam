import logging
from aiogram import Router, F, Bot
from aiogram.types import Message, ChatMemberUpdated
from aiogram.filters import ChatMemberUpdatedFilter, JOIN_TRANSITION, Command
from bot.database.db import get_settings, save_settings, remove_group
from config import DEFAULT_SETTINGS

logger = logging.getLogger(__name__)
router = Router()

router.message.filter(F.chat.type.in_({"group", "supergroup"}))


@router.my_chat_member(ChatMemberUpdatedFilter(JOIN_TRANSITION))
async def bot_added_to_group(event: ChatMemberUpdated, bot: Bot):
    """Бот добавлен в группу — регистрируем её."""
    chat_id = event.chat.id
    chat_title = event.chat.title or "Группа"

    # Регистрируем только если бот стал администратором
    new_status = event.new_chat_member.status
    if new_status not in ("administrator", "creator"):
        return

    settings = await get_settings(chat_id)
    await save_settings(chat_id, chat_title, settings)
    logger.info(f"Добавлен в группу: {chat_title} ({chat_id})")

    try:
        await bot.send_message(
            chat_id,
            f"👋 <b>AntiFlood Bot активирован!</b>\n\n"
            f"Настройки по умолчанию:\n"
            f"• Лимит: <b>{settings['max_messages']}</b> сообщений за <b>1 сутки</b>\n"
            f"• Режим: <b>Мут на 1 сутки</b>\n\n"
            f"Администраторы могут изменить настройки командой /antiflood"
        )
    except Exception as e:
        logger.warning(f"Не удалось отправить приветствие: {e}")


@router.my_chat_member()
async def bot_status_changed(event: ChatMemberUpdated):
    """Бот разжалован или удалён — убираем группу из базы."""
    new_status = event.new_chat_member.status
    old_status = event.old_chat_member.status

    # Был админом, стал кем-то другим — убираем
    if old_status in ("administrator", "creator") and new_status not in ("administrator", "creator"):
        await remove_group(event.chat.id)
        logger.info(f"Удалён/разжалован в группе {event.chat.id}, группа удалена из базы")


@router.message(F.new_chat_members)
async def new_member(message: Message, bot: Bot):
    """Обновляем название группы."""
    if message.chat.title:
        settings = await get_settings(message.chat.id)
        await save_settings(message.chat.id, message.chat.title, settings)


@router.message(Command("start"))
async def delete_start_in_group(message: Message):
    """Удаляем /start который Telegram шлёт при добавлении через deep link."""
    try:
        await message.delete()
    except Exception:
        pass
