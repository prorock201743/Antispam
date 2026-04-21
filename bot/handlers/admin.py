import logging
from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, ChatMemberAdministrator, ChatMemberOwner
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from bot.database.db import (
    get_settings, save_settings, update_setting,
    get_all_groups, reset_violations, remove_group
)
from bot.keyboards.keyboards import (
    settings_menu, interval_keyboard, maxmsg_keyboard,
    mode_keyboard, mute_duration_keyboard, groups_keyboard,
    whitelist_keyboard, confirm_reset_keyboard
)
from bot.middlewares.antiflood import _format_seconds
from config import DEFAULT_SETTINGS, BOT_ADMINS

logger = logging.getLogger(__name__)
router = Router()


@router.message.outer_middleware()
async def private_only_middleware(handler, event, data):
    # Проверяем только сообщения в личке
    if event.chat.type != "private":
        return await handler(event, data)
    user_id = event.from_user.id if event.from_user else None
    if user_id not in BOT_ADMINS:
        await event.answer(
            "👋 Привет, этот бот приватный.\n"
            "Если хочешь им воспользоваться — отпиши разработчику: @maxxzol"
        )
        return
    return await handler(event, data)


class WaitingInput(StatesGroup):
    wl_add = State()
    wl_remove = State()
    phrase_add = State()
    phrase_remove = State()


# ─── Вспомогательные функции ───────────────────────────────────────────────

async def is_admin(bot: Bot, chat_id: int, user_id: int) -> bool:
    if user_id in BOT_ADMINS:
        return True
    try:
        member = await bot.get_chat_member(chat_id, user_id)
        return isinstance(member, (ChatMemberAdministrator, ChatMemberOwner))
    except Exception:
        return False


async def safe_edit(call: CallbackQuery, text: str, reply_markup=None):
    """Редактирует сообщение и всегда закрывает spinner на кнопке."""
    try:
        await call.message.edit_text(text, reply_markup=reply_markup)
    except Exception:
        pass
    finally:
        await call.answer()


def settings_text(chat_id: int, chat_title: str, s: dict) -> str:
    mode_labels = {"mute": "🔇 Мут", "kick": "👟 Кик", "ban": "🚫 Бан"}
    wl = s.get("whitelist", [])
    return (
        f'⚙️ <b>Настройки группы "{chat_title}"</b>\n'
        f'<code>({chat_id})</code>\n\n'
        f'📅 Интервал: <b>{_format_seconds(s["interval"])}</b>\n'
        f'💬 Разрешено сообщений: <b>{s["max_messages"]}</b>\n'
        f'⚡ Режим ограничения: <b>{mode_labels.get(s["restriction_mode"], s["restriction_mode"])}</b>\n'
        f'⏳ Длительность мута: <b>{"Навсегда" if s["mute_duration"] == 0 else _format_seconds(s["mute_duration"])}</b>\n'
        f'🗑 Автоудаление сообщений бота: <b>{"вкл" if s["auto_delete_bot_msgs"] else "выкл"} '
        f'({s["auto_delete_delay"]} сек.)</b>\n'
        f'👥 Белый список: <b>{len(wl)} ID</b>'
    )


# ─── Команда /start в ЛС ───────────────────────────────────────────────────

@router.message(Command("start"), F.chat.type == "private")
async def cmd_start(message: Message, bot: Bot):
    args = message.text.split(maxsplit=1)[1] if len(message.text.split()) > 1 else ""

    if args == "connect":
        bot_info = await bot.get_me()
        bot_username = bot_info.username or ""
        all_groups = await get_all_groups()
        my_groups = [
            g for g in all_groups
            if await is_admin(bot, g["chat_id"], message.from_user.id)
        ]
        text = (
            "✅ <b>Бот успешно добавлен в группу!</b>\n\n"
            f"📋 <b>Ваши группы ({len(my_groups)}):</b>\nВыберите группу для настройки:"
        ) if my_groups else (
            "⏳ <b>Ожидаю подключения...</b>\n\n"
            "Если вы только что добавили бота, нажмите "
            "<b>🔄 Обновить список</b> через несколько секунд."
        )
        await message.answer(text, reply_markup=groups_keyboard(my_groups, bot_username))
        return

    await message.answer(
        "👋 <b>AntiFlood Bot</b>\n\n"
        "Добавьте меня в группу и назначьте администратором.\n\n"
        "Команды:\n"
        "/groups — управление группами\n"
        "/help — справка"
    )


@router.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(
        "📖 <b>Справка AntiFlood Bot</b>\n\n"
        "<b>В личных сообщениях:</b>\n"
        "/groups — список ваших групп и настройки\n\n"
        "<b>В группе:</b>\n"
        "/antiflood — открыть настройки (только для администраторов)\n"
        "/stats — статистика нарушений\n"
        "/reset @username — сбросить нарушения пользователя\n\n"
        "<b>Режимы ограничения:</b>\n"
        "🔇 Мут — запрет писать на время\n"
        "👟 Кик — исключить из группы\n"
        "🚫 Бан — заблокировать навсегда"
    )


# ─── Список групп ─────────────────────────────────────────────────────────

@router.message(Command("groups"), F.chat.type == "private")
async def show_groups(message: Message, bot: Bot):
    await _show_groups(message, bot)


@router.callback_query(F.data == "af_groups")
async def show_groups_callback(call: CallbackQuery, bot: Bot):
    await _show_groups(call, bot)


async def _show_groups(event: Message | CallbackQuery, bot: Bot):
    user_id = event.from_user.id
    all_groups = await get_all_groups()

    # Фильтруем только те группы, где пользователь — администратор
    my_groups = []
    for g in all_groups:
        # Проверяем права самого бота в чате
        try:
            bot_info = await bot.get_me()
            bot_member = await bot.get_chat_member(g["chat_id"], bot_info.id)
            if bot_member.status not in ("administrator", "creator"):
                await remove_group(g["chat_id"])
                continue
        except Exception:
            await remove_group(g["chat_id"])
            continue

        # Проверяем права пользователя
        if user_id in BOT_ADMINS or await is_admin(bot, g["chat_id"], user_id):
            my_groups.append(g)

    bot_info = await bot.get_me()
    bot_username = bot_info.username or ""

    if my_groups:
        text = f"📋 <b>Ваши группы ({len(my_groups)}):</b>\nВыберите группу для настройки:"
    else:
        text = (
            "📋 <b>Ваши группы (0):</b>\n\n"
            "У вас пока нет подключённых групп.\n\n"
            "Нажмите <b>➕ Подключить новый чат</b> — выберите группу, "
            "и бот автоматически запросит права администратора."
        )

    kb = groups_keyboard(my_groups, bot_username)

    if isinstance(event, CallbackQuery):
        try:
            await event.message.edit_text(text, reply_markup=kb)
        except Exception:
            pass  # MessageNotModified — содержимое не изменилось, это нормально
        finally:
            await event.answer()  # всегда закрываем spinner на кнопке
    else:
        await event.answer(text, reply_markup=kb)


# ─── Настройки группы ─────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("af_settings:"))
async def show_settings(call: CallbackQuery, bot: Bot):
    chat_id = int(call.data.split(":")[1])

    if not await is_admin(bot, chat_id, call.from_user.id):
        return await call.answer("⛔ Нет прав!", show_alert=True)

    try:
        chat = await bot.get_chat(chat_id)
        chat_title = chat.title or "Группа"
    except Exception:
        chat_title = "Группа"

    settings = await get_settings(chat_id)
    text = settings_text(chat_id, chat_title, settings)
    kb = settings_menu(chat_id, settings)

    await call.message.edit_text(text, reply_markup=kb)
    await call.answer()


# ─── Команда /antiflood прямо в группе ────────────────────────────────────

@router.message(Command("antiflood"), F.chat.type.in_({"group", "supergroup"}))
async def cmd_antiflood_group(message: Message, bot: Bot):
    if not await is_admin(bot, message.chat.id, message.from_user.id):
        return await message.reply("⛔ Только для администраторов!")

    chat_id = message.chat.id
    settings = await get_settings(chat_id)
    text = settings_text(chat_id, message.chat.title, settings)
    kb = settings_menu(chat_id, settings)
    await message.reply(text, reply_markup=kb)


# ─── Переключение вкл/выкл ────────────────────────────────────────────────

@router.callback_query(F.data.startswith("af_toggle:"))
async def toggle_enabled(call: CallbackQuery, bot: Bot):
    chat_id = int(call.data.split(":")[1])
    if not await is_admin(bot, chat_id, call.from_user.id):
        return await call.answer("⛔ Нет прав!", show_alert=True)

    settings = await get_settings(chat_id)
    settings["enabled"] = not settings.get("enabled", True)

    try:
        chat = await bot.get_chat(chat_id)
        title = chat.title or "Группа"
    except Exception:
        title = "Группа"

    await save_settings(chat_id, title, settings)
    status = "включён ✅" if settings["enabled"] else "выключен ❌"
    await call.answer(f"Антифлуд {status}", show_alert=True)

    text = settings_text(chat_id, title, settings)
    await call.message.edit_text(text, reply_markup=settings_menu(chat_id, settings))


# ─── Интервал ─────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("af_interval:"))
async def choose_interval(call: CallbackQuery, bot: Bot):
    chat_id = int(call.data.split(":")[1])
    if not await is_admin(bot, chat_id, call.from_user.id):
        return await call.answer("⛔ Нет прав!", show_alert=True)

    await call.message.edit_text(
        "⏱ <b>Выберите интервал подсчёта сообщений:</b>",
        reply_markup=interval_keyboard(chat_id)
    )
    await call.answer()


@router.callback_query(F.data.startswith("af_set_interval:"))
async def set_interval(call: CallbackQuery, bot: Bot):
    _, chat_id_str, val_str = call.data.split(":")
    chat_id = int(chat_id_str)
    if not await is_admin(bot, chat_id, call.from_user.id):
        return await call.answer("⛔ Нет прав!", show_alert=True)

    try:
        chat = await bot.get_chat(chat_id)
        title = chat.title or "Группа"
    except Exception:
        title = "Группа"

    await update_setting(chat_id, title, "interval", int(val_str))
    await call.answer(f"✅ Интервал: {_format_seconds(int(val_str))}", show_alert=True)

    settings = await get_settings(chat_id)
    await call.message.edit_text(
        settings_text(chat_id, title, settings),
        reply_markup=settings_menu(chat_id, settings)
    )


# ─── Кол-во сообщений ─────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("af_maxmsg:"))
async def choose_maxmsg(call: CallbackQuery, bot: Bot):
    chat_id = int(call.data.split(":")[1])
    if not await is_admin(bot, chat_id, call.from_user.id):
        return await call.answer("⛔ Нет прав!", show_alert=True)

    await call.message.edit_text(
        "💬 <b>Выберите максимальное количество сообщений за интервал:</b>",
        reply_markup=maxmsg_keyboard(chat_id)
    )
    await call.answer()


@router.callback_query(F.data.startswith("af_set_maxmsg:"))
async def set_maxmsg(call: CallbackQuery, bot: Bot):
    _, chat_id_str, val_str = call.data.split(":")
    chat_id = int(chat_id_str)
    if not await is_admin(bot, chat_id, call.from_user.id):
        return await call.answer("⛔ Нет прав!", show_alert=True)

    try:
        chat = await bot.get_chat(chat_id)
        title = chat.title or "Группа"
    except Exception:
        title = "Группа"

    await update_setting(chat_id, title, "max_messages", int(val_str))
    await call.answer(f"✅ Лимит: {val_str} сообщений", show_alert=True)

    settings = await get_settings(chat_id)
    await call.message.edit_text(
        settings_text(chat_id, title, settings),
        reply_markup=settings_menu(chat_id, settings)
    )


# ─── Режим ограничения ────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("af_mode:"))
async def choose_mode(call: CallbackQuery, bot: Bot):
    chat_id = int(call.data.split(":")[1])
    if not await is_admin(bot, chat_id, call.from_user.id):
        return await call.answer("⛔ Нет прав!", show_alert=True)

    await call.message.edit_text(
        "⚡ <b>Выберите режим ограничения при флуде:</b>",
        reply_markup=mode_keyboard(chat_id)
    )
    await call.answer()


@router.callback_query(F.data.startswith("af_set_mode:"))
async def set_mode(call: CallbackQuery, bot: Bot):
    parts = call.data.split(":")
    chat_id = int(parts[1])
    mode = parts[2]
    if not await is_admin(bot, chat_id, call.from_user.id):
        return await call.answer("⛔ Нет прав!", show_alert=True)

    try:
        chat = await bot.get_chat(chat_id)
        title = chat.title or "Группа"
    except Exception:
        title = "Группа"

    await update_setting(chat_id, title, "restriction_mode", mode)
    labels = {"mute": "Мут", "kick": "Кик", "ban": "Бан"}
    await call.answer(f"✅ Режим: {labels.get(mode, mode)}", show_alert=True)

    settings = await get_settings(chat_id)
    await call.message.edit_text(
        settings_text(chat_id, title, settings),
        reply_markup=settings_menu(chat_id, settings)
    )


# ─── Длительность мута ────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("af_mutedur:"))
async def choose_mute_duration(call: CallbackQuery, bot: Bot):
    chat_id = int(call.data.split(":")[1])
    if not await is_admin(bot, chat_id, call.from_user.id):
        return await call.answer("⛔ Нет прав!", show_alert=True)

    await call.message.edit_text(
        "⏳ <b>Выберите длительность мута:</b>",
        reply_markup=mute_duration_keyboard(chat_id)
    )
    await call.answer()


@router.callback_query(F.data.startswith("af_set_mutedur:"))
async def set_mute_duration(call: CallbackQuery, bot: Bot):
    _, chat_id_str, val_str = call.data.split(":")
    chat_id = int(chat_id_str)
    if not await is_admin(bot, chat_id, call.from_user.id):
        return await call.answer("⛔ Нет прав!", show_alert=True)

    try:
        chat = await bot.get_chat(chat_id)
        title = chat.title or "Группа"
    except Exception:
        title = "Группа"

    val = int(val_str)
    await update_setting(chat_id, title, "mute_duration", val)
    label = "Навсегда" if val == 0 else _format_seconds(val)
    await call.answer(f"✅ Длительность мута: {label}", show_alert=True)

    settings = await get_settings(chat_id)
    await call.message.edit_text(
        settings_text(chat_id, title, settings),
        reply_markup=settings_menu(chat_id, settings)
    )


# ─── Автоудаление сообщений бота ──────────────────────────────────────────

@router.callback_query(F.data.startswith("af_autodel:"))
async def toggle_autodel(call: CallbackQuery, bot: Bot):
    chat_id = int(call.data.split(":")[1])
    if not await is_admin(bot, chat_id, call.from_user.id):
        return await call.answer("⛔ Нет прав!", show_alert=True)

    settings = await get_settings(chat_id)
    settings["auto_delete_bot_msgs"] = not settings.get("auto_delete_bot_msgs", True)

    try:
        chat = await bot.get_chat(chat_id)
        title = chat.title or "Группа"
    except Exception:
        title = "Группа"

    await save_settings(chat_id, title, settings)
    status = "включено" if settings["auto_delete_bot_msgs"] else "выключено"
    await call.answer(f"Автоудаление {status}", show_alert=True)

    await call.message.edit_text(
        settings_text(chat_id, title, settings),
        reply_markup=settings_menu(chat_id, settings)
    )


# ─── Белый список ─────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("af_whitelist:"))
async def show_whitelist(call: CallbackQuery, bot: Bot):
    chat_id = int(call.data.split(":")[1])
    if not await is_admin(bot, chat_id, call.from_user.id):
        return await call.answer("⛔ Нет прав!", show_alert=True)

    settings = await get_settings(chat_id)
    wl = settings.get("whitelist", [])
    wl_text = "\n".join([f"  • <code>{uid}</code>" for uid in wl]) if wl else "  — пусто"

    await call.message.edit_text(
        f"👥 <b>Белый список</b> (не ограничиваются):\n{wl_text}",
        reply_markup=whitelist_keyboard(chat_id)
    )
    await call.answer()


@router.callback_query(F.data.startswith("af_wl_add:"))
async def wl_add_start(call: CallbackQuery, state: FSMContext, bot: Bot):
    chat_id = int(call.data.split(":")[1])
    if not await is_admin(bot, chat_id, call.from_user.id):
        return await call.answer("⛔ Нет прав!", show_alert=True)

    await state.set_state(WaitingInput.wl_add)
    await state.update_data(chat_id=chat_id)
    await call.message.edit_text(
        "✏️ Введите <b>Telegram ID</b> пользователя для добавления в белый список:"
    )
    await call.answer()


@router.message(WaitingInput.wl_add)
async def wl_add_input(message: Message, state: FSMContext, bot: Bot):
    data = await state.get_data()
    chat_id = data["chat_id"]

    if not message.text or not message.text.strip().lstrip("-").isdigit():
        return await message.answer("❌ Введите корректный числовой ID.")

    user_id_to_add = int(message.text.strip())
    settings = await get_settings(chat_id)
    wl = settings.get("whitelist", [])

    if user_id_to_add in wl:
        await message.answer(f"ℹ️ ID <code>{user_id_to_add}</code> уже в белом списке.")
    else:
        wl.append(user_id_to_add)
        settings["whitelist"] = wl
        try:
            chat = await bot.get_chat(chat_id)
            title = chat.title or "Группа"
        except Exception:
            title = "Группа"
        await save_settings(chat_id, title, settings)
        await message.answer(f"✅ ID <code>{user_id_to_add}</code> добавлен в белый список.")

    await state.clear()


@router.callback_query(F.data.startswith("af_wl_remove:"))
async def wl_remove_start(call: CallbackQuery, state: FSMContext, bot: Bot):
    chat_id = int(call.data.split(":")[1])
    if not await is_admin(bot, chat_id, call.from_user.id):
        return await call.answer("⛔ Нет прав!", show_alert=True)

    await state.set_state(WaitingInput.wl_remove)
    await state.update_data(chat_id=chat_id)
    await call.message.edit_text(
        "✏️ Введите <b>Telegram ID</b> для удаления из белого списка:"
    )
    await call.answer()


@router.message(WaitingInput.wl_remove)
async def wl_remove_input(message: Message, state: FSMContext, bot: Bot):
    data = await state.get_data()
    chat_id = data["chat_id"]

    if not message.text or not message.text.strip().lstrip("-").isdigit():
        return await message.answer("❌ Введите корректный числовой ID.")

    user_id_to_rm = int(message.text.strip())
    settings = await get_settings(chat_id)
    wl = settings.get("whitelist", [])

    if user_id_to_rm not in wl:
        await message.answer(f"ℹ️ ID <code>{user_id_to_rm}</code> не найден в белом списке.")
    else:
        wl.remove(user_id_to_rm)
        settings["whitelist"] = wl
        try:
            chat = await bot.get_chat(chat_id)
            title = chat.title or "Группа"
        except Exception:
            title = "Группа"
        await save_settings(chat_id, title, settings)
        await message.answer(f"✅ ID <code>{user_id_to_rm}</code> удалён из белого списка.")

    await state.clear()


# ─── Сброс настроек ───────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("af_reset:"))
async def reset_confirm(call: CallbackQuery, bot: Bot):
    chat_id = int(call.data.split(":")[1])
    if not await is_admin(bot, chat_id, call.from_user.id):
        return await call.answer("⛔ Нет прав!", show_alert=True)

    await call.message.edit_text(
        "⚠️ <b>Сбросить все настройки до значений по умолчанию?</b>",
        reply_markup=confirm_reset_keyboard(chat_id)
    )
    await call.answer()


@router.callback_query(F.data.startswith("af_confirm_reset:"))
async def do_reset(call: CallbackQuery, bot: Bot):
    chat_id = int(call.data.split(":")[1])
    if not await is_admin(bot, chat_id, call.from_user.id):
        return await call.answer("⛔ Нет прав!", show_alert=True)

    try:
        chat = await bot.get_chat(chat_id)
        title = chat.title or "Группа"
    except Exception:
        title = "Группа"

    await save_settings(chat_id, title, dict(DEFAULT_SETTINGS))
    await call.answer("✅ Настройки сброшены!", show_alert=True)

    settings = await get_settings(chat_id)
    await call.message.edit_text(
        settings_text(chat_id, title, settings),
        reply_markup=settings_menu(chat_id, settings)
    )


# ─── Статистика ───────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("af_stats:"))
async def show_stats(call: CallbackQuery, bot: Bot):
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    chat_id = int(call.data.split(":")[1])
    if not await is_admin(bot, chat_id, call.from_user.id):
        return await call.answer("⛔ Нет прав!", show_alert=True)

    import aiosqlite
    from bot.database.db import DB_PATH
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT user_id, count, violations FROM message_counts WHERE chat_id=? ORDER BY violations DESC LIMIT 10",
            (chat_id,)
        ) as cur:
            rows = await cur.fetchall()

    if not rows:
        text = "📊 <b>Статистика пуста</b>"
    else:
        lines = ["📊 <b>Топ нарушителей:</b>\n"]
        for i, (uid, cnt, viol) in enumerate(rows, 1):
            lines.append(f"{i}. <code>{uid}</code> — {viol} нарушений (сообщений: {cnt})")
        text = "\n".join(lines)

    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="« Назад", callback_data=f"af_settings:{chat_id}")
    ]])
    await call.message.edit_text(text, reply_markup=kb)
    await call.answer()


# ─── /reset в группе ──────────────────────────────────────────────────────

@router.message(Command("reset"), F.chat.type.in_({"group", "supergroup"}))
async def cmd_reset_user(message: Message, bot: Bot):
    if not await is_admin(bot, message.chat.id, message.from_user.id):
        return

    target = None
    if message.reply_to_message:
        target = message.reply_to_message.from_user
    elif message.entities:
        for ent in message.entities:
            if ent.type == "mention":
                username = message.text[ent.offset + 1:ent.offset + ent.length]
                try:
                    chat_member = await bot.get_chat_member(message.chat.id, f"@{username}")
                    target = chat_member.user
                except Exception:
                    pass
                break

    if not target:
        return await message.reply("Используйте команду в ответ на сообщение пользователя.")

    await reset_violations(message.chat.id, target.id)
    await message.reply(f"✅ Нарушения <b>{target.full_name}</b> сброшены.")


@router.message(Command("adminslist"), F.chat.type == "private")
async def cmd_admins_list(message: Message):
    if not BOT_ADMINS:
        await message.answer("Список администраторов пуст.")
        return
    lines = "\n".join([f"• <code>{uid}</code>" for uid in BOT_ADMINS])
    await message.answer(f"👥 <b>Администраторы бота:</b>\n\n{lines}")


# ─── Запрещённые фразы ────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("af_phrases:"))
async def show_phrases(call: CallbackQuery, bot: Bot):
    chat_id = int(call.data.split(":")[1])
    if not await is_admin(bot, chat_id, call.from_user.id):
        await call.answer("⛔ Нет прав!", show_alert=True)
        return
    settings = await get_settings(chat_id)
    phrases = settings.get("banned_phrases", [])
    phrases_text = "\n".join([f"  • <code>{p}</code>" for p in phrases]) if phrases else "  — пусто"
    from bot.keyboards.keyboards import phrases_keyboard
    await safe_edit(
        call,
        f"🚫 <b>Запрещённые фразы:</b>\n{phrases_text}\n\n"
        f"Сообщения содержащие эти фразы будут автоматически удалены.",
        phrases_keyboard(chat_id)
    )


@router.callback_query(F.data.startswith("af_phrase_add:"))
async def phrase_add_start(call: CallbackQuery, state: FSMContext, bot: Bot):
    chat_id = int(call.data.split(":")[1])
    if not await is_admin(bot, chat_id, call.from_user.id):
        await call.answer("⛔ Нет прав!", show_alert=True)
        return
    await state.set_state(WaitingInput.phrase_add)
    await state.update_data(chat_id=chat_id)
    await safe_edit(call, "✏️ Введите фразу для блокировки (регистр не важен):")


@router.message(WaitingInput.phrase_add)
async def phrase_add_input(message: Message, state: FSMContext, bot: Bot):
    data = await state.get_data()
    chat_id = data["chat_id"]
    phrase = message.text.strip().lower() if message.text else None
    if not phrase:
        return await message.answer("❌ Введите текст фразы.")
    settings = await get_settings(chat_id)
    phrases = settings.get("banned_phrases", [])
    if phrase in phrases:
        await message.answer(f"ℹ️ Фраза <code>{phrase}</code> уже в списке.")
    else:
        phrases.append(phrase)
        settings["banned_phrases"] = phrases
        try:
            title = (await bot.get_chat(chat_id)).title or "Группа"
        except Exception:
            title = "Группа"
        await save_settings(chat_id, title, settings)
        await message.answer(f"✅ Фраза <code>{phrase}</code> добавлена.")
    await state.clear()


@router.callback_query(F.data.startswith("af_phrase_remove:"))
async def phrase_remove_start(call: CallbackQuery, state: FSMContext, bot: Bot):
    chat_id = int(call.data.split(":")[1])
    if not await is_admin(bot, chat_id, call.from_user.id):
        await call.answer("⛔ Нет прав!", show_alert=True)
        return
    await state.set_state(WaitingInput.phrase_remove)
    await state.update_data(chat_id=chat_id)
    await safe_edit(call, "✏️ Введите фразу для удаления из списка:")


@router.message(WaitingInput.phrase_remove)
async def phrase_remove_input(message: Message, state: FSMContext, bot: Bot):
    data = await state.get_data()
    chat_id = data["chat_id"]
    phrase = message.text.strip().lower() if message.text else None
    if not phrase:
        return await message.answer("❌ Введите текст фразы.")
    settings = await get_settings(chat_id)
    phrases = settings.get("banned_phrases", [])
    if phrase not in phrases:
        await message.answer(f"ℹ️ Фраза <code>{phrase}</code> не найдена в списке.")
    else:
        phrases.remove(phrase)
        settings["banned_phrases"] = phrases
        try:
            title = (await bot.get_chat(chat_id)).title or "Группа"
        except Exception:
            title = "Группа"
        await save_settings(chat_id, title, settings)
        await message.answer(f"✅ Фраза <code>{phrase}</code> удалена.")
    await state.clear()

# ─── noop ─────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "noop")
async def noop(call: CallbackQuery):
    await call.answer()
